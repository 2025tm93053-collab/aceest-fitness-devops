// Declarative pipeline: clean workspace -> checkout -> clean Docker build -> containerized tests.
// Requirements on the Jenkins agent: Linux, git and a running Docker daemon the jenkins user may use.
pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        timeout(time: 20, unit: 'MINUTES')
    }

    // Fallback trigger. A GitHub webhook (see README) makes builds start immediately on push.
    triggers {
        pollSCM('H/5 * * * *')
    }

    environment {
        IMAGE_NAME = 'aceest-fitness'
        IMAGE_TAG  = "build-${env.BUILD_NUMBER}"
    }

    stages {
        stage('Clean workspace') {
            steps {
                deleteDir()
            }
        }

        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Build') {
            steps {
                // --no-cache and --pull make this a clean build from the latest sources and base image.
                sh 'docker build --no-cache --pull --target runtime -t ${IMAGE_NAME}:${IMAGE_TAG} .'
                sh 'docker build --no-cache --target test -t ${IMAGE_NAME}:${IMAGE_TAG}-test .'
            }
        }

        stage('Test (Pytest in container)') {
            steps {
                sh 'docker run --name aceest-test-${BUILD_NUMBER} ${IMAGE_NAME}:${IMAGE_TAG}-test pytest -q --junitxml=/tmp/junit.xml'
            }
            post {
                always {
                    sh '''
                        mkdir -p reports
                        docker cp aceest-test-${BUILD_NUMBER}:/tmp/junit.xml reports/junit.xml || true
                        docker rm -f aceest-test-${BUILD_NUMBER} || true
                    '''
                    junit allowEmptyResults: true, testResults: 'reports/junit.xml'
                }
            }
        }

        stage('Smoke test (runtime image)') {
            steps {
                sh '''
                    docker run -d --name aceest-smoke-${BUILD_NUMBER} ${IMAGE_NAME}:${IMAGE_TAG}
                    for attempt in $(seq 1 20); do
                        if docker exec aceest-smoke-${BUILD_NUMBER} python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=3).status == 200 else 1)"; then
                            echo "Health check passed"
                            exit 0
                        fi
                        sleep 1
                    done
                    docker logs aceest-smoke-${BUILD_NUMBER}
                    exit 1
                '''
            }
            post {
                always {
                    sh 'docker rm -f aceest-smoke-${BUILD_NUMBER} || true'
                }
            }
        }
    }

    post {
        always {
            sh 'docker image rm -f ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:${IMAGE_TAG}-test || true'
        }
        success {
            echo 'Build, containerized tests and smoke test passed.'
        }
        failure {
            echo 'Pipeline failed - see the stage logs above.'
        }
    }
}

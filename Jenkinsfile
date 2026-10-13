
pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        timeout(time: 20, unit: 'MINUTES')
    }

    triggers {
        pollSCM('H/5 * * * *')
    }

    environment {
        IMAGE_NAME = 'aceest-fitness'
        IMAGE_TAG = "build-${env.BUILD_NUMBER}"
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
                bat 'docker build --no-cache --pull --target runtime -t %IMAGE_NAME%:%IMAGE_TAG% .'
                bat 'docker build --no-cache --target test -t %IMAGE_NAME%:%IMAGE_TAG%-test .'
            }
        }

        stage('Test (Pytest in container)') {
            steps {
                bat 'docker run --name aceest-test-%BUILD_NUMBER% %IMAGE_NAME%:%IMAGE_TAG%-test pytest -q --junitxml=/tmp/junit.xml'
            }
            post {
                always {
                    bat '''
                        if not exist reports mkdir reports
                        docker cp aceest-test-%BUILD_NUMBER%:/tmp/junit.xml reports/junit.xml
                        docker rm -f aceest-test-%BUILD_NUMBER%
                        exit /b 0
                    '''
                    junit allowEmptyResults: true, testResults: 'reports/junit.xml'
                }
            }
        }

        stage('Smoke test (runtime image)') {
            steps {
                bat '''
                    docker run -d --name aceest-smoke-%BUILD_NUMBER% %IMAGE_NAME%:%IMAGE_TAG%
                    if errorlevel 1 exit /b 1

                    for /L %%i in (1,1,20) do (
                        docker exec aceest-smoke-%BUILD_NUMBER% python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=3).status == 200 else 1)"
                        if not errorlevel 1 (
                            echo Health check passed
                            exit /b 0
                        )
                        timeout /t 1 /nobreak >NUL
                    )

                    docker logs aceest-smoke-%BUILD_NUMBER%
                    exit /b 1
                '''
            }
            post {
                always {
                    bat 'docker rm -f aceest-smoke-%BUILD_NUMBER% 2>NUL || exit /b 0'
                }
            }
        }
    }

    post {
        always {
            bat 'docker image rm -f %IMAGE_NAME%:%IMAGE_TAG% %IMAGE_NAME%:%IMAGE_TAG%-test 2>NUL || exit /b 0'
        }
        success {
            echo 'Build, containerized tests and smoke test passed.'
        }
        failure {
            echo 'Pipeline failed - see the stage logs above.'
        }
    }
}

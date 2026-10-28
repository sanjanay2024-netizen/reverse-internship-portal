pipeline {
    agent any

    stages {
        stage('Check Python') {
            steps {
                bat 'python --version'
            }
        }

        stage('Install Dependencies') {
            steps {
                bat 'python -m pip install -r requirements.txt'
            }
        }

        stage('Validate Python Code') {
            steps {
                bat 'python -m compileall -q app.py'
            }
        }
    }

    post {
        success {
            echo 'Reverse Internship Portal build succeeded!'
        }
        failure {
            echo 'Build failed. Check Console Output.'
        }
    }
}
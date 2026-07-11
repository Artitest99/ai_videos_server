@echo off
echo Activating virtual environment...

:: Change "venv" to whatever your virtual environment folder is named
call ..\.venv\Scripts\activate

echo Starting Django development server...
start http://127.0.0.1:8000

:: Run the server and keep the window open
cmd /k python manage.py runserver
docker build -t nadobot .
timeout /t 2

REM Load environment variables from .env file
for /f "tokens=*" %%i in (.env) do set %%i

docker run -d ^
    -e TOKEN=%TOKEN% ^
    -e URL=%URL% ^
    -e MODELS=%MODELS% ^
    --name nadobot nadobot

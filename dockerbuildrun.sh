docker build -t nadobot .
sleep 2

# Load environment variables from .env file
if [ -f .env ]; then
    export $(cat .env | xargs)
fi

docker run -d \
    -e TOKEN=$TOKEN \
    -e URL=$URL \
    -e MODELS=$MODELS \
    --name nadobot nadobot

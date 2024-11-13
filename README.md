# NadoBot

[![CI/CD Pipeline](https://github.com/Zachdehooge/NadoBot/actions/workflows/CICD.yml/badge.svg)](https://github.com/Zachdehooge/NadoBot/actions/workflows/CICD.yml)

## Models

- Model declaration can be done under `MODELS` in the `.env` file. Your choices are `2022`, `2022abs`, `2024`, and `2024abs` or you can leave it blank and receive all four of them

## Contributing

- After cloning the repo run `pip install -r requirements.txt` to install the dependencies for this repo
- Rename the file called `example.env` to `.env` and put your discord bot token next to `TOKEN=`

* Any questions feel free to open a discussion or issue!

## Docker Containerization

- In order to run Nadobot through Docker you will need to perform the following
  - Build the Image: `docker build -t Nadobot .`
  - Run the Container: `docker run -d \ -e TOKEN=your_token_here \ -e URL=http://data.nadocast.com/ \ -e MODELS=your_model_here \ --name Nadobot Nadobot`

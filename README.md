# NadoBot

[![CI/CD Pipeline](https://github.com/Zachdehooge/NadoBot/actions/workflows/CICD.yml/badge.svg)](https://github.com/Zachdehooge/NadoBot/actions/workflows/CICD.yml)

![Alt](https://repobeats.axiom.co/api/embed/33a13497022ac4ec16c0609dfa21f1481cfd4a24.svg 'Repobeats analytics image')

## Models

- Model declaration can be done under `MODELS` in the `.env` file. Your choices are `2022`, `2022abs`, `2024`, and `2024abs` or you can leave it blank and receive all four of them

## Build From Source

 - `git clone https://github.com/Zachdehooge/NadoBot.git`
 - cd into the cloned directory and run`python -m venv venv`
 - Ensure Discord is running
 - Create a bot at: https://discord.com/developers/applications
 - Click on the bot you created -> Bot -> Copy token
 - Set envars in the `.env` file
    - `TOKEN` with the value being your discord bot token
    - `URL` with the value being `http://data.nadocast.com/`
    - `MODELS` (can be left blank)
 - Run `python3 main.py`

## Docker Containerization

- In order to run Nadobot through Docker you will need to perform the following from where the `Dockerfile` is located:

  - Clone the repo and cd into the directory
  - Build the Image: `docker build -t Nadobot .`
  - Run the Container: `docker run -d \ -e TOKEN=your_token_here \ -e URL=http://data.nadocast.com/ \ -e MODELS=your_model_here \ --name Nadobot Nadobot`
    - Alternatively in the Docker GUI, set the envars there before creating the container

- Alternatively
  - Go to Dockerhub on Docker desktop and run the image

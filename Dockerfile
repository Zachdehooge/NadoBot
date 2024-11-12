# Use an official Python runtime as a parent image
FROM python:3.13.0

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file first to leverage Docker's caching for dependencies.
COPY requirements.txt ./

# Install dependencies.
RUN pip install --no-cache-dir -r requirements.txt

# Copy the bot code into the container.
COPY . .
# Run app.py when the container launches
CMD ["python3", "main.py"]


# To run the application in Docker: docker run -it --rm --name my-running-app my-python-app
# Reference: https://www.geeksforgeeks.org/setting-up-docker-for-python-projects-a-step-by-step-guide/
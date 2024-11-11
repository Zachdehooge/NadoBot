# Use an official Python runtime as a parent image
FROM python:3.13.0-bullseye

# Set the working directory in the container
WORKDIR /usr/src/app

# Copy the current directory contents into the container at /usr/src/app
COPY . .

# Install any needed packages specified in requirements.txt 
RUN chmod +x /usr/src/app/build.sh
RUN ./build.sh
# Run app.py when the container launches
CMD ["python", "main.py"]


# To run the application in Docker: docker run -it --rm --name my-running-app my-python-app
# Reference: https://www.geeksforgeeks.org/setting-up-docker-for-python-projects-a-step-by-step-guide/
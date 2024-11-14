# Use an official Python runtime as a parent image
FROM python:3.12

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
# Use an official, lightweight Python runtime as a parent image
FROM python:3.12-slim

# Set environment variables to prevent Python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory inside the container
WORKDIR /app

# Copy only the requirements file first to leverage Docker cache layers
COPY requirements.txt .

# Install the dependencies specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Inform Docker that the container listens on port 8000 at runtime
EXPOSE 8000

# Run the FastAPI app with Uvicorn
# Use the faster, production-ready server from the uvicorn package
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

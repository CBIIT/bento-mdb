FROM prefecthq/prefect-client:3.3.4.dev2-python3.11@sha256:f54420e24410a28c13b903cf0bb6342d4010755d6acb05bc13fa0431ad4d6f7e

# Install OpenJDK
RUN apt-get update && \
    apt-get install -y openjdk-17-jdk wget git && \
    apt-get clean

# Set JAVA_HOME environment variable
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PATH=$JAVA_HOME/bin:$PATH

# Install uv
RUN curl -Ls https://astral.sh/uv/install.sh | bash
ENV PATH="/root/.cargo/bin:$PATH"

# Create app directory
WORKDIR /app

# Download Neo4j JDBC driver
RUN mkdir -p drivers && \
    wget -O drivers/liquibase-neo4j-4.31.1-full.jar https://github.com/liquibase/liquibase-neo4j/releases/download/v4.31.1/liquibase-neo4j-4.31.1-full.jar
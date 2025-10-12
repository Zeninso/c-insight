#!/usr/bin/env python3
"""
Database setup script for C-Insight Capstone Flask application.
This script creates the database schema for PythonAnywhere deployment.
"""

import os
import sys
import mysql.connector
from mysql.connector import Error
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_db_config():
    """Get database configuration from environment variables."""
    config = {
        'host': os.environ.get('MYSQL_HOST', 'localhost'),
        'user': os.environ.get('MYSQL_USER'),
        'password': os.environ.get('MYSQL_PASSWORD'),
        'database': os.environ.get('MYSQL_DB'),
        'port': int(os.environ.get('MYSQL_PORT', 3306)),
        'autocommit': True
    }

    # Check for required environment variables
    required_vars = ['MYSQL_HOST', 'MYSQL_USER', 'MYSQL_PASSWORD', 'MYSQL_DB']
    missing_vars = [var for var in required_vars if not os.environ.get(var)]

    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.info("Please set the following environment variables:")
        logger.info("  MYSQL_HOST: Your MySQL host (e.g., yourusername.mysql.pythonanywhere-services.com)")
        logger.info("  MYSQL_USER: Your MySQL username")
        logger.info("  MYSQL_PASSWORD: Your MySQL password")
        logger.info("  MYSQL_DB: Your database name")
        logger.info("  MYSQL_PORT: MySQL port (default: 3306)")
        sys.exit(1)

    return config

def execute_sql_file(cursor, sql_file_path):
    """Execute SQL commands from a file."""
    try:
        with open(sql_file_path, 'r', encoding='utf-8') as file:
            sql_content = file.read()

        # Split SQL commands by semicolon (basic approach)
        # Note: This won't handle complex cases like procedures with semicolons
        sql_commands = [cmd.strip() for cmd in sql_content.split(';') if cmd.strip()]

        for command in sql_commands:
            if command:  # Skip empty commands
                try:
                    cursor.execute(command)
                    logger.info(f"Executed: {command[:50]}...")
                except Error as e:
                    logger.warning(f"Warning executing command: {e}")
                    logger.warning(f"Command was: {command[:100]}...")

        logger.info("SQL file executed successfully")

    except FileNotFoundError:
        logger.error(f"SQL file not found: {sql_file_path}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error executing SQL file: {e}")
        sys.exit(1)

def create_database_if_not_exists(config):
    """Create database if it doesn't exist."""
    try:
        # Connect without specifying database
        temp_config = config.copy()
        db_name = temp_config.pop('database')

        connection = mysql.connector.connect(**temp_config)
        cursor = connection.cursor()

        # Create database if it doesn't exist
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name}")
        logger.info(f"Database '{db_name}' created or already exists")

        cursor.close()
        connection.close()

    except Error as e:
        logger.error(f"Error creating database: {e}")
        sys.exit(1)

def main():
    """Main function to set up the database."""
    logger.info("Starting database setup for C-Insight Capstone...")

    # Get database configuration
    config = get_db_config()

    # Create database if it doesn't exist
    create_database_if_not_exists(config)

    # Connect to the database
    try:
        connection = mysql.connector.connect(**config)
        cursor = connection.cursor()

        logger.info("Connected to MySQL database")

        # Get the directory of this script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        sql_file_path = os.path.join(script_dir, 'database_schema.sql')

        # Execute the SQL schema file
        execute_sql_file(cursor, sql_file_path)

        # Close connection
        cursor.close()
        connection.close()

        logger.info("Database setup completed successfully!")
        logger.info("You can now run your Flask application.")

    except Error as e:
        logger.error(f"Error connecting to MySQL: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

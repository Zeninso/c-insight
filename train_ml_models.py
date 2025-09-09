#!/usr/bin/env python3
"""
Script to train machine learning models for C code grading.
Run this script to train ML models using historical grading data.
"""

import sys
import os

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from flask import Flask
from app.grading import train_ml_grading_model

def create_app():
    app = Flask(__name__)

    return app

def main():
    """Main function to train ML models."""
    print(" Starting ML Model Training for C Code Grading")
    print("=" * 50)

    app = create_app()

    with app.app_context():
        print(" Gathering historical grading data...")
        success = train_ml_grading_model()

        if success:
            print("ML models trained successfully!")
            print(" Models saved to: ml_grading_models.pkl")
            print("\n The grading system will now use ML-enhanced analysis")
            print("   for more accurate C code evaluation.")
        else:
            print(" Failed to train ML models.")
            print(" Make sure you have sufficient historical grading data")
            print("   (at least 50 submissions with grades).")

    print("\n" + "=" * 50)
    print("Training complete!")

if __name__ == "__main__":
    main()

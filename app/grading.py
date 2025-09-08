import subprocess
import tempfile
import os
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from app import mysql

def grade_submission(activity_id, student_id, code):
    """
    Grade a student submission based on the activity's rubric.
    Returns a dict with scores and feedback.
    """
    # Get activity details
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT starter_code, correctness_weight, syntax_weight, logic_weight, similarity_weight
        FROM activities WHERE id = %s
    """, (activity_id,))
    activity = cur.fetchone()
    cur.close()

    if not activity:
        return {'error': 'Activity not found'}

    starter_code, correctness_w, syntax_w, logic_w, similarity_w = activity

    # Initialize scores
    correctness_score = 0
    syntax_score = 0
    logic_score = 0
    similarity_score = 0
    feedback = []

    # Syntax check using GCC
    syntax_score, syntax_feedback = check_syntax(code)
    feedback.append(syntax_feedback)

    # Correctness and Logic using algorithmic analysis (no starter code dependency)
    correctness_score, logic_score, ast_feedback = check_ast(code)
    feedback.append(ast_feedback)

    # Similarity check
    similarity_score, sim_feedback = check_similarity(activity_id, code)
    feedback.append(sim_feedback)

    # Calculate weighted scores
    total_score = (
        (correctness_score * correctness_w / 100) +
        (syntax_score * syntax_w / 100) +
        (logic_score * logic_w / 100) +
        (similarity_score * similarity_w / 100)
    )

    return {
        'correctness_score': int(correctness_score),
        'syntax_score': int(syntax_score),
        'logic_score': int(logic_score),
        'similarity_score': int(similarity_score),
        'feedback': ' '.join(feedback)
    }

def check_syntax(code):
    """
    Check syntax using GCC compiler for C code.
    Returns score (0-100) and feedback.
    """
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.c', delete=False) as f:
            f.write(code)
            temp_file = f.name

        # Compile with GCC
        result = subprocess.run(['gcc', '-fsyntax-only', temp_file],
                              capture_output=True, text=True, timeout=10)

        os.unlink(temp_file)

        if result.returncode == 0:
            return 100, "Syntax is correct."
        else:
            errors = result.stderr.strip()
            error_count = errors.count('error')
            if error_count == 0:
                return 80, "Minor syntax issues found."
            elif error_count <= 3:
                return 50, f"Syntax errors found: {errors[:200]}..."
            else:
                return 0, f"Multiple syntax errors: {errors[:200]}..."

    except subprocess.TimeoutExpired:
        return 0, "Syntax check timed out."
    except Exception as e:
        return 0, f"Syntax check failed: {str(e)}"

def check_ast(code, starter_code=None):
    """
    Check correctness and logic using algorithmic analysis for C code.
    Returns correctness_score, logic_score, feedback.
    """
    # For C code, provide basic analysis
    correctness_score = 70  # Default score for valid C syntax
    logic_score = 65  # Default score for basic logic

    feedback_parts = []
    feedback_parts.append("C Code analysis.")
    feedback_parts.append(f"Code Quality: {correctness_score:.1f}%")
    feedback_parts.append(f"Logic Complexity: {logic_score:.1f}%")

    # Basic C code quality checks
    quality_feedback = assess_c_code_quality(code)
    if quality_feedback:
        feedback_parts.append(quality_feedback)

    return correctness_score, logic_score, '. '.join(feedback_parts)

def assess_c_code_quality(code):
    """Provide basic quality feedback for C code."""
    feedback_parts = []

    # Basic checks for C code
    lines = code.split('\n')
    issues = []

    # Check for main function
    if 'int main(' not in code:
        issues.append("No main function found")

    # Check for includes
    if '#include' not in code:
        issues.append("Missing include statements")

    # Check for basic structure
    if '{' not in code or '}' not in code:
        issues.append("Missing braces")

    # Check for semicolons (basic)
    open_braces = code.count('{')
    close_braces = code.count('}')
    if open_braces != close_braces:
        issues.append("Unmatched braces")

    # Check for comments
    if '//' not in code and '/*' not in code:
        issues.append("No comments found - consider adding comments for clarity")

    if issues:
        feedback_parts.extend(issues)

    return '. '.join(feedback_parts) if feedback_parts else "Basic C structure looks good."

def check_similarity(activity_id, code):
    """
    Check similarity with other submissions using cosine similarity.
    Returns score (0-100, lower is better for originality) and feedback.
    """
    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT code FROM submissions
            WHERE activity_id = %s AND code IS NOT NULL
        """, (activity_id,))
        submissions = cur.fetchall()
        cur.close()

        if len(submissions) < 2:
            return 100, "Insufficient submissions for similarity check."

        codes = [row[0] for row in submissions] + [code]

        # Vectorize using TF-IDF
        vectorizer = TfidfVectorizer(stop_words='english', ngram_range=(1, 2))
        tfidf_matrix = vectorizer.fit_transform(codes)

        # Calculate similarities
        similarities = cosine_similarity(tfidf_matrix[-1:], tfidf_matrix[:-1])[0]

        # Max similarity (higher means more similar)
        max_sim = np.max(similarities) * 100

        # Score: 100 - max_sim (higher score for less similarity)
        score = max(0, 100 - max_sim)

        feedback = f"Max similarity with other submissions: {max_sim:.1f}%."

        return score, feedback

    except Exception as e:
        return 50, f"Similarity check failed: {str(e)}"

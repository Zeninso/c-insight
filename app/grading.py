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
    # Analyze C code structure and logic
    correctness_score = analyze_c_code_correctness(code)
    logic_score = analyze_c_code_logic(code)

    feedback_parts = []
    feedback_parts.append("C Code analysis.")
    feedback_parts.append(f"Code Quality: {correctness_score:.1f}%")
    feedback_parts.append(f"Logic Complexity: {logic_score:.1f}%")

    # Basic C code quality checks
    quality_feedback = assess_c_code_quality(code)
    if quality_feedback:
        feedback_parts.append(quality_feedback)

    # Additional detailed correctness and logic analysis feedback
    detailed_feedback = analyze_c_code_detailed_feedback(code)
    if detailed_feedback:
        feedback_parts.append(detailed_feedback)

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

def analyze_c_code_correctness(code):
    """
    Analyze C code correctness based on specific criteria.
    Returns a score from 0-100.
    """
    score = 50  # Base score
    feedback_parts = []

    # Criteria 1: Variable Declaration and Usage (20 points)
    # Check for proper variable declarations
    var_declarations = len([line for line in code.split('\n') if any(type in line for type in ['int ', 'char ', 'float ', 'double '])])
    if var_declarations > 0:
        score += 15
        feedback_parts.append(f"Found {var_declarations} variable declarations")
    else:
        feedback_parts.append("No variable declarations found")

    # Criteria 2: Function Structure (20 points)
    # Check for proper function definitions
    func_count = code.count('(') - code.count('main(')  # Count function calls, exclude main
    if func_count > 0:
        score += 15
        feedback_parts.append(f"Code uses {func_count} functions")
    else:
        feedback_parts.append("No custom functions defined")

    # Criteria 3: Return Statements (15 points)
    # Check for proper return statements
    return_count = code.count('return ')
    if return_count > 0:
        score += 10
        feedback_parts.append(f"Found {return_count} return statements")
    else:
        feedback_parts.append("Missing return statements")

    # Criteria 4: Semicolon Usage (15 points)
    # Check for proper statement termination
    lines = code.split('\n')
    total_lines = len([line for line in lines if line.strip()])
    semicolon_lines = len([line for line in lines if line.strip().endswith(';')])
    if total_lines > 0:
        semicolon_ratio = semicolon_lines / total_lines
        score += int(semicolon_ratio * 15)
        feedback_parts.append(f"Semicolon usage: {semicolon_ratio:.1f}")

    # Criteria 5: Code Organization (15 points)
    # Check for proper indentation and structure
    indented_lines = len([line for line in lines if line.startswith('    ') or line.startswith('\t')])
    if total_lines > 0:
        indent_ratio = indented_lines / total_lines
        score += int(indent_ratio * 15)
        feedback_parts.append(f"Code indentation: {indent_ratio:.1f}")

    # Criteria 6: Memory Management (15 points)
    # Check for pointers and memory operations
    pointer_usage = code.count('*') + code.count('&') + code.count('malloc') + code.count('free')
    if pointer_usage > 0:
        score += 10
        feedback_parts.append(f"Memory management operations: {pointer_usage}")
    else:
        feedback_parts.append("No memory management detected")

    return min(100, max(0, score))

def analyze_c_code_logic(code):
    """
    Analyze C code logic complexity and flow.
    Returns a score from 0-100.
    """
    score = 50  # Base score
    feedback_parts = []

    # Criteria 1: Control Flow Complexity (25 points)
    # Analyze loops and conditionals
    if_count = code.count('if ') + code.count('else if')
    loop_count = code.count('for ') + code.count('while ') + code.count('do ')
    switch_count = code.count('switch ')

    total_control = if_count + loop_count + switch_count
    if total_control > 0:
        # Reward reasonable complexity, penalize excessive complexity
        if total_control <= 5:
            score += 20
            feedback_parts.append(f"Good control flow: {total_control} control structures")
        elif total_control <= 10:
            score += 15
            feedback_parts.append(f"Moderate complexity: {total_control} control structures")
        else:
            score += 5
            feedback_parts.append(f"High complexity: {total_control} control structures")
    else:
        feedback_parts.append("No control flow structures found")

    # Criteria 2: Algorithm Indicators (20 points)
    # Check for algorithmic patterns
    algorithm_indicators = 0
    if 'sort' in code.lower() or 'search' in code.lower():
        algorithm_indicators += 1
    if '%' in code:  # Modulo operations
        algorithm_indicators += 1
    if 'sqrt' in code or 'pow' in code:  # Math functions
        algorithm_indicators += 1
    if '&&' in code or '||' in code:  # Logical operators
        algorithm_indicators += 1

    score += min(20, algorithm_indicators * 5)
    feedback_parts.append(f"Algorithm indicators: {algorithm_indicators}")

    # Criteria 3: Data Processing (15 points)
    # Check for arrays and data manipulation
    array_usage = code.count('[') + code.count(']')
    if array_usage > 0:
        score += 10
        feedback_parts.append(f"Array operations: {array_usage}")
    else:
        feedback_parts.append("No array operations detected")

    # Criteria 4: Error Handling (15 points)
    # Check for basic error handling patterns
    error_patterns = code.count('NULL') + code.count('if (') + code.count('else')
    if error_patterns > 0:
        score += 10
        feedback_parts.append(f"Error handling patterns: {error_patterns}")
    else:
        feedback_parts.append("Limited error handling")

    # Criteria 5: Code Efficiency (15 points)
    # Check for potential efficiency issues
    nested_loops = code.count('for (') + code.count('while (') - 1  # Subtract 1 for main loop
    if nested_loops <= 0:
        score += 15
        feedback_parts.append("No nested loops - good efficiency")
    elif nested_loops <= 2:
        score += 10
        feedback_parts.append(f"Moderate nesting: {nested_loops} levels")
    else:
        score += 5
        feedback_parts.append(f"Deep nesting detected: {nested_loops} levels")

    return min(100, max(0, score))

def analyze_c_code_detailed_feedback(code):
    """
    Provide detailed feedback on C code analysis.
    Returns a string with detailed analysis.
    """
    feedback_parts = []

    # Analyze code length and complexity
    lines = [line for line in code.split('\n') if line.strip()]
    code_length = len(lines)

    if code_length < 10:
        feedback_parts.append("Code is quite short - consider adding more functionality")
    elif code_length > 50:
        feedback_parts.append("Code is lengthy - consider breaking into functions")
    else:
        feedback_parts.append("Code length is appropriate")

    # Check for specific C programming patterns
    patterns_found = []

    if 'printf(' in code:
        patterns_found.append("Uses output functions")
    if 'scanf(' in code:
        patterns_found.append("Uses input functions")
    if '#include <stdio.h>' in code:
        patterns_found.append("Includes standard I/O library")
    if 'int main(' in code:
        patterns_found.append("Has main function")
    if '{' in code and '}' in code:
        patterns_found.append("Proper code blocks")

    if patterns_found:
        feedback_parts.append("Positive patterns: " + ", ".join(patterns_found))

    # Check for potential issues
    issues = []

    if code.count('{') != code.count('}'):
        issues.append("Brace mismatch detected")
    if 'return 0;' not in code and 'return ' in code:
        issues.append("Consider returning 0 from main")
    if len([line for line in lines if len(line) > 80]) > 0:
        issues.append("Some lines are very long - consider breaking them")

    if issues:
        feedback_parts.append("Areas for improvement: " + ", ".join(issues))

    return ". ".join(feedback_parts) if feedback_parts else "Code structure analysis complete."

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

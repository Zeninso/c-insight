import subprocess
import tempfile
import os
import re
import datetime
import json
from difflib import SequenceMatcher
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
import numpy as np
import pickle
import logging
import hashlib
from app import mysql
import MySQLdb


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CodeGrader:
    def __init__(self):
        self.ml_models = None
        self.additional_keywords = []
        self.load_ml_models()
    
    def load_ml_models(self):
        """Load ML models if available"""
        try:
            if os.path.exists('ml_grading_models.pkl'):
                with open('ml_grading_models.pkl', 'rb') as f:
                    self.ml_models = pickle.load(f)
                logger.info("ML models loaded successfully")
        except Exception as e:
            logger.error(f"Error loading ML models: {str(e)}")
            self.ml_models = None

    def parse_test_cases(self, activity_id):
        """Parse test cases from activity data."""
        try:
            # Ensure activity_id is a valid integer
            try:
                activity_id = int(activity_id)
            except (TypeError, ValueError):
                logger.error(f"Invalid activity_id: {activity_id}")
                return []

            cur = mysql.connection.cursor(cursorclass=MySQLdb.cursors.DictCursor)
            cur.execute("SELECT test_cases_json FROM activities WHERE id = %s", (activity_id,))
            result = cur.fetchone()
            cur.close()

            if not result or not result['test_cases_json']:
                return []

            # Parse JSON test cases
            test_cases = json.loads(result['test_cases_json'])
            if not isinstance(test_cases, list):
                return []

            # Validate test case format
            validated_cases = []
            for case in test_cases:
                if isinstance(case, dict) and 'input' in case and 'output' in case:
                    validated_cases.append({
                        'input': str(case['input']),
                        'expected': str(case['output'])
                    })

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"Error parsing test cases: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"Database error in parse_test_cases: {str(e)}")
            return []

        return validated_cases

    def compile_and_run_code(self, code, test_input):
        """Compile student's C code and run with test input."""
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                # Write code to file
                code_file = os.path.join(temp_dir, 'student_code.c')
                with open(code_file, 'w') as f:
                    f.write(code)

                # Compile the code
                exe_file = os.path.join(temp_dir, 'student_code.exe')
                compile_result = subprocess.run(
                    ['gcc', code_file, '-o', exe_file],
                    capture_output=True, text=True, timeout=10
                )

                if compile_result.returncode != 0:
                    return None, f"Compilation failed: {compile_result.stderr[:200]}"

                # Run with test input
                run_result = subprocess.run(
                    [exe_file],
                    input=test_input,
                    capture_output=True, text=True, timeout=5
                )

                if run_result.returncode != 0:
                    return None, f"Runtime error: {run_result.stderr[:200]}"

                return run_result.stdout.strip(), None

        except subprocess.TimeoutExpired:
            return None, "Execution timed out"
        except Exception as e:
            logger.error(f"Error in compile_and_run_code: {str(e)}")
            return None, f"Execution error: {str(e)}"

    def clean_prompts(self, output, additional_keywords=None):
        """Remove common prompt lines from output."""
        if not output:
            return output

        # Normalize newlines and work line by line
        lines = output.split('\n')
        cleaned_lines = []

        # Base prompt phrases to remove (kept intentionally broad).
        prompt_keywords = [
            'enter your', 'please enter', 'enter name', 'enter age', 'enter value', 'enter number',
            'please enter', 'input', 'enter', 'prompt', 'type here', 'enter here', 'input here',
            'output', 'result', 'answer', 'response', 'reply'
        ]

        if additional_keywords:
            if isinstance(additional_keywords, str):
                additional_keywords = [kw.strip() for kw in additional_keywords.split(',')]
            prompt_keywords.extend(additional_keywords)

        # Remove prompt phrases from each line while preserving following text.
        # Use longest-first so multi-word phrases match before shorter words.
        for line in lines:
            cleaned_line = line
            for keyword in sorted(set(prompt_keywords), key=lambda k: -len(k)):
                # Match the keyword case-insensitively, allow optional punctuation
                # and whitespace after the phrase (e.g. 'Enter your name: ', 'input - ').
                try:
                    pattern = r"(?i)" + re.escape(keyword) + r"[\s\:\-\,\.;!\(\)]*"
                    cleaned_line = re.sub(pattern, '', cleaned_line)
                except re.error:
                    cleaned_line = cleaned_line.replace(keyword, '')

            # Collapse multiple spaces and trim
            cleaned_line = re.sub(r'\s+', ' ', cleaned_line).strip()
            if cleaned_line:
                cleaned_lines.append(cleaned_line)

        return '\n'.join(cleaned_lines)

    def compare_outputs_flexible(self, actual, expected):
        """Compare outputs with flexible pattern matching (fully case-insensitive)."""
        if not actual or not expected:
            return actual.strip().lower() == expected.strip().lower()

        # Normalize whitespace
        actual = actual.strip()
        expected = expected.strip()

        # Clean prompts from both actual and expected output
        actual = self.clean_prompts(actual, self.additional_keywords)
        expected = self.clean_prompts(expected, self.additional_keywords)

        # Make all comparisons case-insensitive
        actual_lower = actual.lower()
        expected_lower = expected.lower()

        # Exact match first (case-insensitive)
        if actual_lower == expected_lower:
            return True

        # Try to extract just the answer part from actual output
        # Look for the expected output within the actual output (case-insensitive)
        if expected_lower in actual_lower:
            return True

        # Split into lines and compare line by line (case-insensitive)
        actual_lines = [line.strip().lower() for line in actual.split('\n') if line.strip()]
        expected_lines = [line.strip().lower() for line in expected.split('\n') if line.strip()]

        # If expected has fewer lines, check if expected appears in any actual line
        if len(expected_lines) == 1 and len(actual_lines) >= 1:
            for actual_line in actual_lines:
                if expected_lines[0] in actual_line:
                    return True

        if len(actual_lines) != len(expected_lines):
            return False

        # Compare each line with some flexibility
        for actual_line, expected_line in zip(actual_lines, expected_lines):
            if not self.compare_single_line(actual_line, expected_line):
                return False

        return True
    def remove_punctuation(self, text):
        """Remove common punctuation marks from text."""
        # Define punctuation to ignore
        punctuation_to_remove = '.!?,;:\'"()-'
        for char in punctuation_to_remove:
            text = text.replace(char, '')
        return text.strip()

    def compare_single_line(self, actual, expected):
        """Compare single lines with flexible matching (fully case-insensitive)."""
        # Exact match (case-insensitive)
        if actual.lower() == expected.lower():
            return True

        # Numeric comparison with tolerance for floating point
        try:
            actual_num = float(actual)
            expected_num = float(expected)
            # Allow small tolerance for floating point comparisons
            return abs(actual_num - expected_num) < 1e-6
        except ValueError:
            pass

        # Check if expected contains actual or vice versa (case-insensitive)
        if expected.lower() in actual.lower() or actual.lower() in expected.lower():
            return True

        # Compare ignoring punctuation (case-insensitive)
        actual_no_punct = self.remove_punctuation(actual.lower())
        expected_no_punct = self.remove_punctuation(expected.lower())
        
        if actual_no_punct == expected_no_punct and len(actual_no_punct) > 0:
            # Match found after removing punctuation
            logger.info(f"Punctuation-tolerant match: '{actual}' matches '{expected}'")
            return True

        return False

    def grade_submission(self, activity_id, student_id, code):
        """
        Grade a student submission based on the activity's rubric.
        """
        try:
            # Get activity details
            cur = mysql.connection.cursor(cursorclass=MySQLdb.cursors.DictCursor)
            cur.execute("""
                SELECT title, description, instructions, starter_code, due_date,
                        correctness_weight, syntax_weight, logic_weight, similarity_weight
                FROM activities WHERE id = %s
            """, (activity_id,))
            activity = cur.fetchone()
            cur.close()

            if not activity:
                return {'error': 'Activity not found'}

            # Get submission time
            cur = mysql.connection.cursor(cursorclass=MySQLdb.cursors.DictCursor)
            cur.execute("SELECT submitted_at FROM submissions WHERE activity_id = %s AND student_id = %s ORDER BY submitted_at DESC LIMIT 1", (activity_id, student_id))
            submission = cur.fetchone()
            cur.close()

            if submission and submission['submitted_at']:
                submitted_at = submission['submitted_at']
                if isinstance(submitted_at, str):
                    submitted_at = datetime.datetime.strptime(submitted_at, '%Y-%m-%d %H:%M:%S')
            else:
                submitted_at = datetime.datetime.now()

            title = activity['title']
            description = activity['description']
            instructions = activity['instructions']
            starter_code = activity['starter_code']
            due_date = activity['due_date']
            try:
                correctness_w = float(activity['correctness_weight'])
            except (ValueError, TypeError):
                correctness_w = 25.0
            try:
                syntax_w = float(activity['syntax_weight'])
            except (ValueError, TypeError):
                syntax_w = 25.0
            try:
                logic_w = float(activity['logic_weight'])
            except (ValueError, TypeError):
                logic_w = 25.0
            try:
                similarity_w = float(activity['similarity_weight'])
            except (ValueError, TypeError):
                similarity_w = 25.0

            # Convert due_date if it's a string
            if due_date and isinstance(due_date, str):
                try:
                    due_date = datetime.datetime.strptime(due_date, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    due_date = None

            # Calculate overdue penalty
            overdue_penalty = 0
            if due_date and submitted_at and submitted_at > due_date:
                # Calculate total seconds overdue
                total_seconds_overdue = (submitted_at - due_date).total_seconds()
    
                # Calculate weeks overdue based on seconds (1 week = 604,800 seconds)
                seconds_per_week = 7 * 24 * 3600  # 604,800
                weeks_overdue = total_seconds_overdue // seconds_per_week
                if total_seconds_overdue % seconds_per_week > 0:  # Partial week counts as full week
                    weeks_overdue += 1
    
                overdue_penalty = weeks_overdue * 10
            

            # Extract requirements from activity text for semantic analysis
            activity_text_for_requirements = f"{description} {instructions}" if description or instructions else ""
            requirements = self.extract_activity_requirements(activity_text_for_requirements) if activity_text_for_requirements else None
            requirement_score = 100

            # Syntax check using GCC
            syntax_score, syntax_feedback = self.check_syntax(code)

            # If syntax score is below threshold, assign zero to all scores and skip further checks
            test_details = []  # Initialize for all paths
            if syntax_score < 85:
                correctness_score = 0
                syntax_score = 0
                logic_score = 0
                similarity_score = 0
                ast_feedback = "Submission has syntax errors; grading scores set to zero."
                sim_feedback = "Similarity check skipped due to syntax errors."
            else:
                # Dynamic testing with test cases
                test_cases = self.parse_test_cases(activity_id)
                test_correctness_score = 0
                test_feedback = ""

                if test_cases:
                    if len(test_cases) == 1:
                        # Single test case, use original method
                        passed_tests = 0
                        total_tests = len(test_cases)
                        test_details = []

                        for i, test_case in enumerate(test_cases, 1):
                            actual_output, error = self.compile_and_run_code(code, test_case['input'])

                            if error:
                                test_details.append(f"Test {i}: Failed - {error}")
                            else:
                                # Clean prompts from the actual output to remove echoes/prompts
                                cleaned_actual = self.clean_prompts(actual_output, self.additional_keywords)
                                expected = test_case['expected']

                                if self.compare_outputs_flexible(cleaned_actual, expected):
                                    passed_tests += 1
                                    test_details.append(f"Test {i}: Passed")
                                else:
                                    # Add helpful diagnostic info for failures
                                    logger.warning(f"Test {i} failed. Expected: '{expected}' | Actual (cleaned): '{cleaned_actual[:200]}'")
                                    test_details.append(f"Test {i}: Failed")

                        test_correctness_score = (passed_tests / total_tests) * 100 if total_tests > 0 else 0
                        test_feedback = f"Test Cases: {passed_tests}/{total_tests} passed ({test_correctness_score:.1f}%). " + " | ".join(test_details)
                    else:
                        # Multiple test cases: run each test input in isolation. This is
                        # more robust than concatenating inputs and parsing combined output.
                        passed_tests = 0
                        test_details = []

                        for i, test_case in enumerate(test_cases, 1):
                            inp = test_case['input']
                            expected = test_case['expected']

                            actual_output, error = self.compile_and_run_code(code, inp)
                            if error:
                                test_details.append(f"Test {i}: Failed - {error}")
                                continue

                            cleaned_actual = self.clean_prompts(actual_output, self.additional_keywords)

                            if self.compare_outputs_flexible(cleaned_actual, expected):
                                passed_tests += 1
                                test_details.append(f"Test {i}: Passed")
                            else:
                                logger.warning(f"Test {i} failed. Expected: '{expected}' | Actual (cleaned): '{cleaned_actual[:200]}'")
                                test_details.append(f"Test {i}: Failed")

                            test_correctness_score = (passed_tests / len(test_cases)) * 100
                            test_feedback = f"Test Cases: {passed_tests}/{len(test_cases)} passed ({test_correctness_score:.1f}%). " + " | ".join(test_details)
                else:
                    test_feedback = "No test cases defined for this activity - using static analysis only."
                    test_correctness_score = 50  # Neutral score when no tests available

                # Correctness and Logic analysis
                activity_text = f"{description} {instructions}" if description or instructions else ""
                static_correctness_score, logic_score, ast_feedback = self.check_ast_with_requirements(
                    code, requirements, requirement_score, activity_text
                )


                # Correctness is based entirely on test case results, Logic is based on AST analysis
                correctness_score = test_correctness_score
                ast_feedback = f"{test_feedback}, {ast_feedback}"

                # Similarity check
                similarity_score, sim_feedback = self.check_similarity(activity_id, code, student_id)

            # Update feedback with final scores
            ast_feedback = f"Correctness: {correctness_score:.1f}%, Semantic: {logic_score:.1f}%, Syntax: {syntax_score:.1f}%. {ast_feedback}"

            # Apply overdue penalty to individual criteria
            if overdue_penalty > 0:
                total_weight = correctness_w + syntax_w + logic_w + similarity_w
                if total_weight > 0:
                    penalty_correctness = round(overdue_penalty * (correctness_w / total_weight), 1)
                    penalty_syntax = round(overdue_penalty * (syntax_w / total_weight), 1)
                    penalty_logic = round(overdue_penalty * (logic_w / total_weight), 1)
                    penalty_similarity = round(overdue_penalty * (similarity_w / total_weight), 1)

                    correctness_score = (correctness_score * correctness_w / 100)
                    syntax_score = (syntax_score * syntax_w / 100)
                    logic_score = (logic_score * logic_w / 100)
                    similarity_score = (similarity_score * similarity_w / 100)

                    correctness_score = max(0, correctness_score - penalty_correctness)
                    syntax_score = max(0, syntax_score - penalty_syntax)
                    logic_score = max(0, logic_score - penalty_logic)
                    similarity_score = max(0, similarity_score - penalty_similarity)

                    correctness_score = (correctness_score * 100 / correctness_w)
                    syntax_score = (syntax_score * 100 / syntax_w)
                    logic_score = (logic_score * 100 / logic_w)
                    similarity_score = (similarity_score * 100 / similarity_w)

            # Calculate weighted scores
            total_score = (
                (correctness_score * correctness_w / 100) +
                (syntax_score * syntax_w / 100) +
                (logic_score * logic_w / 100) +
                (similarity_score * similarity_w / 100)
            )

            # Compile feedback into structured 4-part format
            feedback_data = self.format_comprehensive_feedback(
                syntax_score, syntax_feedback,
                test_correctness_score, test_details if test_cases else [],
                logic_score, ast_feedback,
                similarity_score, sim_feedback,
                overdue_penalty
            )
            
            # Convert feedback dict to JSON string for database storage
            feedback_json = json.dumps(feedback_data)

            return {
                'correctness_score': int(correctness_score),
                'syntax_score': int(syntax_score),
                'logic_score': int(logic_score),
                'similarity_score': int(similarity_score),
                'requirement_score': int(requirement_score),
                'total_score': int(total_score),
                'feedback': feedback_json
            }

        except Exception as e:
            logger.error(f"Error grading submission: {str(e)}")
            # Return zero scores when grading fails due to errors
            return {
                'correctness_score': 0,
                'syntax_score': 0,
                'logic_score': 0,
                'similarity_score': 0,
                'requirement_score': 0,
                'total_score': 0,
                'feedback': f'Grading failed due to an error: {str(e)}. All scores set to zero.'
            }

    def format_comprehensive_feedback(self, syntax_score, syntax_msg, correctness_score, test_details, 
                                     logic_score, logic_msg, similarity_score, similarity_msg, overdue_penalty):
        """Format feedback into 4 structured sections for students."""
        feedback = {}
        
        # 1. SYNTAX CHECK
        if syntax_score >= 85:
            feedback['syntax'] = {
                'status': 'Correct',
                'message': 'Your code compiles successfully without syntax errors.',
                'score': f"{syntax_score:.0f}%"
            }
        else:
            # Extract specific error from syntax_msg
            error_details = syntax_msg.split('|') if '|' in syntax_msg else [syntax_msg]
            feedback['syntax'] = {
                'status': 'Error Found',
                'message': f'Syntax errors detected: {error_details[0]}',
                'details': error_details,
                'score': f"{syntax_score:.0f}%"
            }
        
        # 2. CORRECTNESS (Test Cases)
        if test_details:
            passed_count = sum(1 for t in test_details if 'Passed' in t)
            total_count = len(test_details)
            
            feedback['correctness'] = {
                'status': f'{passed_count}/{total_count} tests passed',
                'score': f"{correctness_score:.0f}%",
                'test_results': []
            }
            
            for i, test in enumerate(test_details, 1):
                if 'Passed' in test:
                    feedback['correctness']['test_results'].append({
                        'test_number': i,
                        'status': 'Passed',
                        'result': test
                    })
                else:
                    feedback['correctness']['test_results'].append({
                        'test_number': i,
                        'status': 'Failed',
                        'result': test,
                        'explanation': 'Your code output does not match the expected result for this test case'
                    })
            
            if passed_count == total_count:
                feedback['correctness']['message'] = 'All test cases passed! Your code produces correct output.'
            else:
                feedback['correctness']['message'] = f'Some test cases failed. Review the expected vs actual output.'
        else:
            feedback['correctness'] = {
                'status': 'Not Available',
                'message': 'No test cases defined for this activity.',
                'score': f"{correctness_score:.0f}%"
            }
        
        # 3. SEMANTICS/LOGIC CHECK
        logic_details = logic_msg.split('. ') if logic_msg else []
        required_detected = any('MISSING REQUIRED' in detail or 'required' in detail.lower() for detail in logic_details)
        
        feedback['semantics'] = {
            'score': f"{logic_score:.0f}%",
            'details': []
        }
        
        if required_detected:
            feedback['semantics']['status'] = 'Issues Found'
            for detail in logic_details:
                if detail.strip():
                    feedback['semantics']['details'].append(detail.strip())
        else:
            feedback['semantics']['status'] = 'Good'
            feedback['semantics']['message'] = 'Your code uses good programming practices and logic.'
        
        # 4. SIMILARITY CHECK
        feedback['similarity'] = {
            'score': f"{similarity_score:.0f}%",
        }
        
        if 'Insufficient' in similarity_msg:
            feedback['similarity']['status'] = 'Insufficient Data'
            feedback['similarity']['message'] = 'Not enough submissions yet to check similarity.'
        elif similarity_score > 75:
            feedback['similarity']['status'] = 'High Similarity Detected'
            feedback['similarity']['message'] = similarity_msg
            feedback['similarity']['warning'] = 'Please ensure this is your own original work.'
        elif similarity_score > 50:
            feedback['similarity']['status'] = 'Moderate Similarity'
            feedback['similarity']['message'] = similarity_msg
        else:
            feedback['similarity']['status'] = 'Low Similarity'
            feedback['similarity']['message'] = 'Your submission appears to be original.'
        
        # Add overdue penalty if applicable
        if overdue_penalty > 0:
            feedback['penalty'] = {
                'type': 'Overdue',
                'amount': f"{overdue_penalty}%",
                'message': f'Submission was late. {overdue_penalty}% penalty applied.'
            }
        
        return feedback

    def check_syntax(self, code):
        """Check syntax and basic compilation using GCC compiler for C code."""
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.c', delete=False) as f:
                f.write(code)
                temp_file = f.name

            # Compile with GCC syntax check and basic compilation (no linking)
            result = subprocess.run(
                ['gcc', '-Wall', '-Wextra', '-fsyntax-only', temp_file],
                capture_output=True, text=True, timeout=10
            )

            os.unlink(temp_file)

            if result.returncode == 0:
                return 100, "Your Syntax is correct"
            else:
                errors = result.stderr.strip()
                error_lines = errors.split('\n')
                
                # Extract key error information
                detailed_errors = []
                for line in error_lines:
                    if 'error:' in line:
                        # Extract the error type and location
                        parts = line.split('error:')
                        if len(parts) > 1:
                            error_type = parts[1].strip()
                            # Shorten very long error messages
                            if len(error_type) > 100:
                                error_type = error_type[:100] + "..."
                            detailed_errors.append(f"Error: {error_type}")
                
                error_count = len(detailed_errors)
                
                if error_count == 0:
                    return 80, "Minor syntax issues found"
                elif error_count == 1:
                    return 60, f"One error found. {detailed_errors[0]}"
                elif error_count <= 3:
                    error_msg = " | ".join(detailed_errors)
                    return 40, f"{error_count} errors found: {error_msg}"
                else:
                    error_msg = " | ".join(detailed_errors[:3])
                    return 15, f"{error_count} errors found: {error_msg} (and {error_count-3} more)"

        except subprocess.TimeoutExpired:
            return 0, "Syntax check timed out (code may have infinite compilation issues)"
        except FileNotFoundError:
            # Fallback if GCC is not available
            logger.warning("GCC not found, using basic syntax check")
            return self.basic_syntax_check(code)
        except Exception as e:
            logger.error(f"Syntax check failed: {str(e)}")
            # Fallback to basic syntax check
            return self.basic_syntax_check(code)

    def basic_syntax_check(self, code):
        """Basic syntax check when GCC is not available."""
        try:
            score = 100
            issues = []

            # Check for balanced braces
            if code.count('{') != code.count('}'):
                score -= 20
                issues.append("Unbalanced braces")

            # Check for balanced parentheses
            if code.count('(') != code.count(')'):
                score -= 15
                issues.append("Unbalanced parentheses")

            # Check for basic structure
            if 'int main(' not in code:
                score -= 10
                issues.append("Missing main function")

            # Check for semicolons (basic check)
            lines = code.split('\n')
            missing_semicolons = 0
            for line in lines:
                line = line.strip()
                if line and not line.endswith(';') and not line.endswith('{') and not line.endswith('}') and not line.startswith('#') and not line.startswith('//'):
                    # Skip control statements and function declarations
                    if not any(line.startswith(keyword) for keyword in ['if', 'for', 'while', 'do', 'switch', 'else', 'int ', 'char ', 'float ', 'double ', 'void ']):
                        missing_semicolons += 1

            if missing_semicolons > 0:
                score -= min(20, missing_semicolons * 2)
                issues.append(f"Possible missing semicolons ({missing_semicolons} lines)")

            feedback = "Basic syntax check (GCC not available): " + ", ".join(issues) if issues else "Basic syntax appears correct"
            return max(0, score), feedback

        except Exception as e:
            return 0, f"Basic syntax check failed: {str(e)}"

    def check_ast_with_requirements(self, code, requirements, requirement_score, activity_text=None):
        """Check correctness and logic using analysis."""
        correctness_score, logic_score, syntax_score, enhanced_feedback = self.enhanced_ml_grading(code, requirements, activity_text)

        return correctness_score, logic_score, enhanced_feedback

    def enhanced_ml_grading(self, code, requirements=None, activity_text=None):
        """Enhanced grading function combining ML predictions with rule-based analysis."""
        if self.ml_models:
            ml_correctness, ml_logic, ml_syntax, analysis_type = self.predict_grading_scores(code, requirements, activity_text)
        else:
            ml_correctness, ml_logic, ml_syntax, analysis_type = 0, 0, 0, "Rule-based analysis"

        # Get rule-based analysis
        rule_correctness = self.analyze_c_code_correctness(code)
        # analyze_c_code_logic now returns (score, feedback) tuple
        logic_result = self.analyze_c_code_logic(code, requirements, activity_text)
        if isinstance(logic_result, tuple):
            rule_logic, _ = logic_result
        else:
            rule_logic = logic_result
        rule_syntax, _ = self.check_syntax(code)

        # Combine scores
        if analysis_type == "ML-enhanced analysis":
            final_correctness = 0.7 * ml_correctness + 0.3 * rule_correctness
            final_logic = rule_logic  # Use rule-based logic score for better accuracy
            final_syntax = 0.6 * ml_syntax + 0.4 * rule_syntax
        else:
            final_correctness = rule_correctness
            final_logic = rule_logic
            final_syntax = rule_syntax

        return final_correctness, final_logic, final_syntax, self.analyze_c_code_detailed_feedback(code, requirements)

    def predict_grading_scores(self, code, requirements=None, activity_text=None):
        """Use trained ML models to predict grading scores."""
        if not self.ml_models:
            correctness_score = self.analyze_c_code_correctness(code)
            logic_result = self.analyze_c_code_logic(code, requirements, activity_text)
            logic_score = logic_result[0] if isinstance(logic_result, tuple) else logic_result
            syntax_score = self.check_syntax(code)[0]
            return correctness_score, logic_score, syntax_score, "Rule-based analysis"

        try:
            features = self.extract_code_features(code)
            feature_vector = list(features.values())
            
            # Scale features and make predictions
            feature_vector_scaled = self.ml_models['scaler'].transform([feature_vector])
            correctness_pred = self.ml_models['correctness_model'].predict(feature_vector_scaled)[0]
            logic_pred = self.ml_models['logic_model'].predict(feature_vector_scaled)[0]
            syntax_pred = self.ml_models['syntax_model'].predict(feature_vector_scaled)[0]

            # Ensure predictions are within valid range
            correctness_score = max(0, min(100, correctness_pred))
            logic_score = max(0, min(100, logic_pred))
            syntax_score = max(0, min(100, syntax_pred))

            return correctness_score, logic_score, syntax_score, "ML-enhanced analysis"

        except Exception as e:
            logger.error(f"Error in ML prediction: {str(e)}")
            correctness_score = self.analyze_c_code_correctness(code)
            logic_result = self.analyze_c_code_logic(code, requirements, activity_text)
            logic_score = logic_result[0] if isinstance(logic_result, tuple) else logic_result
            syntax_score = self.check_syntax(code)[0]
            return correctness_score, logic_score, syntax_score, "Rule-based analysis"

    def extract_code_features(self, code):
        """Extract enhanced features from C code for machine learning analysis."""
        lines = code.split('\n')
        code_lines = [line.strip() for line in lines if line.strip()]
        
        # Basic counts
        variable_declarations = len([line for line in code_lines if any(t in line for t in ['int ', 'char ', 'float ', 'double '])])
        function_calls = code.count('(') - code.count('main(')
        return_statements = code.count('return ')
        semicolon_count = code.count(';')
        brace_balance = abs(code.count('{') - code.count('}'))
        if_statements = code.count('if ') + code.count('else if')
        loop_statements = code.count('for ') + code.count('while ') + code.count('do ')
        switch_statements = code.count('switch ')
        pointer_operations = code.count('*') + code.count('&')
        memory_functions = code.count('malloc') + code.count('free') + code.count('calloc') + code.count('realloc')
        array_operations = code.count('[') + code.count(']')
        include_statements = code.count('#include')
        stdio_usage = 1 if '#include <stdio.h>' in code else 0
        printf_calls = code.count('printf(')
        scanf_calls = code.count('scanf(')
        comment_lines = code.count('//') + code.count('/*')
        logical_operators = code.count('&&') + code.count('||')
        comparison_operators = code.count('==') + code.count('!=') + code.count('<') + code.count('>') + code.count('<=') + code.count('>=')
        arithmetic_operators = code.count('+') + code.count('-') + code.count('*') + code.count('/') + code.count('%')
        null_checks = code.count('NULL') + code.count('null')

        # Additional features
        # Cyclomatic complexity approximation: count of decision points
        decision_points = if_statements + loop_statements + switch_statements + code.count('case ')
        # Halstead metrics approximation: count operators and operands
        operators = arithmetic_operators + logical_operators + comparison_operators
        operands = variable_declarations + function_calls + return_statements

        # Average line length
        avg_line_length = np.mean([len(line) for line in code_lines]) if code_lines else 0

        features = {
            'total_lines': len(code_lines),
            'code_length': len(code),
            'variable_declarations': variable_declarations,
            'function_calls': function_calls,
            'return_statements': return_statements,
            'semicolon_count': semicolon_count,
            'brace_balance': brace_balance,
            'if_statements': if_statements,
            'loop_statements': loop_statements,
            'switch_statements': switch_statements,
            'pointer_operations': pointer_operations,
            'memory_functions': memory_functions,
            'array_operations': array_operations,
            'include_statements': include_statements,
            'stdio_usage': stdio_usage,
            'printf_calls': printf_calls,
            'scanf_calls': scanf_calls,
            'comment_lines': comment_lines,
            'logical_operators': logical_operators,
            'comparison_operators': comparison_operators,
            'arithmetic_operators': arithmetic_operators,
            'null_checks': null_checks,
            'decision_points': decision_points,
            'operators': operators,
            'operands': operands,
            'cyclomatic_complexity': decision_points + 1,
            'avg_line_length': avg_line_length,
        }
        
        # Calculate derived features
        features['total_control_flow'] = if_statements + loop_statements + switch_statements
        features['nested_loops'] = max(0, loop_statements - 1)
        features['function_complexity'] = features['total_control_flow'] / max(1, function_calls)
        
        return features

    def analyze_c_code_correctness(self, code):
        """Analyze C code correctness with enhanced criteria."""
        score = 70  # Base score

        lines = code.split('\n')
        total_lines = len([line for line in lines if line.strip()])

        # Variable Declaration and Usage
        var_declarations = len([line for line in lines if any(t in line for t in ['int ', 'char ', 'float ', 'double '])])
        score += 15 if var_declarations > 0 else -10

        # Function Structure
        func_count = code.count('(') - code.count('main(')
        score += 15 if func_count > 0 else -10

        # Return Statements
        return_count = code.count('return ')
        score += 10 if return_count > 0 else -5

        # Semicolon Usage
        semicolon_lines = len([line for line in lines if line.strip().endswith(';')])
        if total_lines > 0:
            score += int((semicolon_lines / total_lines) * 15)

        # Code Organization (indentation)
        indented_lines = len([line for line in lines if line.startswith('    ') or line.startswith('\t')])
        if total_lines > 0:
            score += int((indented_lines / total_lines) * 15)

        # Memory Management (pointers and malloc/free)
        pointer_usage = code.count('*') + code.count('&') + code.count('malloc') + code.count('free')
        score += 10 if pointer_usage > 0 else 0

        # Check for balanced braces
        if code.count('{') != code.count('}'):
            score -= 10

        # Check for presence of main function
        if 'int main(' not in code:
            score -= 10

        # Check for presence of return 0 in main
        if 'int main(' in code and 'return 0;' not in code:
            score -= 5

        return min(100, max(0, score))

    def analyze_c_code_logic(self, code, requirements=None, activity_text=None):
        """Analyze C code logic complexity and flow with enhanced semantic and requirement-based criteria."""
        score = 100  # Start with full score, deduct for errors only
        feedback = []

        # 0. CRITICAL CHECK: Detect hardcoded printf-only solutions
        printf_count = code.count('printf(')
        scanf_count = code.count('scanf(')
        variable_count = len([line for line in code.split('\n') if any(t in line for t in ['int ', 'char ', 'float ', 'double '])])
        logic_count = code.count('if ') + code.count('for ') + code.count('while ')
        
        # If code has many printf but minimal input/processing logic, flag it as hardcoded
        if printf_count > 3 and logic_count == 0 and scanf_count == 0:
            score -= 50
            feedback.append("WARNING: Code appears to be hardcoded printf statements without actual logic or input processing")
        elif printf_count > 2 and variable_count < 2 and logic_count == 0:
            score -= 30
            feedback.append("WARNING: Code may be printing hardcoded values without proper variable usage or logic")

        # 1. Requirement-based semantic check - STRICT enforcement
        # First check if requirements parameter was provided (dict-based)
        missing_constructs = []
        requirement_count = 0
        
        if requirements and isinstance(requirements, dict):
            # Use the structured requirements dict
            requirement_checks = [
                ('loops', lambda c: c.count('for ') + c.count('while ') + c.count('do ') > 0, 20),
                ('if_else', lambda c: 'if ' in c and 'else' in c, 20),
                ('functions', lambda c: c.count('(') - c.count('main(') > 0, 20),
                ('arrays', lambda c: '[' in c and ']' in c, 20),
                ('pointers', lambda c: '*' in c or '&' in c, 20),
                ('switch', lambda c: 'switch ' in c, 20),
            ]
            
            for req_name, check, penalty in requirement_checks:
                if requirements.get(req_name, {}).get('required', False):
                    requirement_count += 1
                    if not check(code):
                        score -= penalty
                        missing_constructs.append(req_name)
        
        # Fallback: check activity_text for semantic keywords (more flexible)
        if not missing_constructs and activity_text:
            text_lower = activity_text.lower()
            
            # More flexible keyword matching
            loop_keywords = ['loop', 'for', 'while', 'iterate', 'iteration', 'repeat']
            if_keywords = ['if', 'condition', 'conditional', 'decision', 'check', 'validate']
            func_keywords = ['function', 'method', 'procedure', 'subroutine']
            array_keywords = ['array', 'list', 'collection', 'elements']
            pointer_keywords = ['pointer', 'address', 'reference', 'memory']
            switch_keywords = ['switch', 'case', 'selection']
            
            # Check for any loop requirement keywords
            if any(kw in text_lower for kw in loop_keywords):
                requirement_count += 1
                if not any(x in code for x in ['for ', 'while ', 'do ']):
                    score -= 20
                    missing_constructs.append('loops')
            
            # Check for any if/conditional requirement keywords
            if any(kw in text_lower for kw in if_keywords):
                requirement_count += 1
                if 'if ' not in code:
                    score -= 20
                    missing_constructs.append('if statement')
            
            # Check for function requirement keywords
            if any(kw in text_lower for kw in func_keywords):
                requirement_count += 1
                if code.count('(') - code.count('main(') <= 0:
                    score -= 20
                    missing_constructs.append('functions')
            
            # Check for array requirement keywords
            if any(kw in text_lower for kw in array_keywords):
                requirement_count += 1
                if '[' not in code or ']' not in code:
                    score -= 20
                    missing_constructs.append('arrays')
            
            # Check for pointer requirement keywords
            if any(kw in text_lower for kw in pointer_keywords):
                requirement_count += 1
                if '*' not in code and '&' not in code:
                    score -= 20
                    missing_constructs.append('pointers')
            
            # Check for switch requirement keywords
            if any(kw in text_lower for kw in switch_keywords):
                requirement_count += 1
                if 'switch ' not in code:
                    score -= 20
                    missing_constructs.append('switch')
        
        if missing_constructs:
            feedback.append(f"MISSING REQUIRED: {', '.join(missing_constructs)}")

        # If requirements are specified and code is missing them, significantly lower the score
        if requirement_count > 0 and missing_constructs:
            missing_ratio = len(missing_constructs) / requirement_count
            if missing_ratio > 0.5:  # Missing more than 50% of required constructs
                score = min(score, 40)  # Cap score to max 40
                feedback.append(f"Critical: More than half of required constructs are missing")

        # 2. General logic scoring (enhanced)
        # Control Flow Complexity - Check for potential issues
        if_count = code.count('if ') + code.count('else if')
        loop_count = code.count('for ') + code.count('while ') + code.count('do ')
        switch_count = code.count('switch ')
        total_control = if_count + loop_count + switch_count
        if total_control == 0 and requirement_count == 0:  # Only penalize if no requirements specified
            score -= 10
            feedback.append("No control flow statements detected (if, loop, switch)")

        # Check for potential infinite loops
        infinite_loop_penalty = self.check_infinite_loops(code)
        if infinite_loop_penalty > 0:
            feedback.append(f"Potential infinite loop detected (-{infinite_loop_penalty})")
        score -= infinite_loop_penalty

        # Check for proper loop initialization and bounds
        if loop_count > 0:
            loop_quality_score = self.check_loop_quality(code)
            if loop_quality_score < 0:
                feedback.append("Loop initialization or bounds may be incorrect")
            score += loop_quality_score

        # Enhanced logic checks for semantic practices
        # Check for proper variable initialization and usage
        var_logic_score = self.check_variable_logic(code)
        if var_logic_score < 0:
            feedback.append("Variable initialization or usage issues detected")
        score += var_logic_score

        # Check for logical consistency and potential errors
        logic_consistency_score = self.check_enhanced_logical_consistency(code)
        if logic_consistency_score < 0:
            feedback.append("Logical consistency issues detected")
        score += logic_consistency_score

        # Check for proper nesting and structure
        nesting_score = self.check_nesting_structure(code)
        if nesting_score < 0:
            feedback.append("Nesting/indentation issues detected")
        score += nesting_score

        # Check for unreachable code patterns
        unreachable_score = self.check_unreachable_code(code)
        if unreachable_score < 0:
            feedback.append("Unreachable code detected")
        score += unreachable_score

        # Check for proper operator usage
        operator_score = self.check_operator_usage(code)
        if operator_score < 0:
            feedback.append("Operator usage issues detected")
        score += operator_score

        # Check for memory safety
        memory_score = self.check_memory_safety(code)
        if memory_score < 0:
            feedback.append("Memory safety issues detected")
        score += memory_score

        # Bonus for good practices
        if 'return 0;' in code:
            score += 2
        if '#include <stdio.h>' in code:
            score += 2
        if 'int main(' in code:
            score += 2

        # Cap score and return feedback
        score = min(100, max(0, score))
        if feedback:
            return score, ". ".join(feedback)
        else:
            return score, "Logic/semantics checks passed."


    def check_nesting_structure(self, code):
        """Check for proper nesting of control structures."""
        score = 0
        lines = code.split('\n')
        indent_levels = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Calculate indentation level
            indent = len(line) - len(stripped)
            indent_levels.append(indent)

            # Check for control structures
            if stripped.startswith(('if ', 'for ', 'while ', 'do ', 'switch ')):
                # Should have proper indentation for nested content
                pass  # This is a basic check; more complex nesting analysis could be added

        # Check for consistent indentation
        if indent_levels:
            avg_indent = sum(indent_levels) / len(indent_levels)
            consistent_indent = sum(1 for level in indent_levels if level % 4 == 0) / len(indent_levels)
            if consistent_indent > 0.8:  # 80% consistent
                score += 5

        return max(0, min(10, score))

    def check_unreachable_code(self, code):
        """Check for unreachable code patterns."""
        score = 0
        lines = code.split('\n')

        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('return ') or stripped == 'break;' or stripped == 'continue;':
                # Check if there's code after this that might be unreachable
                j = i + 1
                while j < len(lines):
                    next_line = lines[j].strip()
                    if next_line and not next_line.startswith('//') and not next_line.startswith('/*'):
                        # Found code after return/break/continue
                        if not next_line.endswith('{') and not next_line.startswith('}'):
                            score -= 3  # Potential unreachable code
                        break
                    j += 1

        return max(-10, min(5, score))  # Cap the score

    def check_algorithm_quality(self, code):
        """Check for proper algorithm implementation patterns."""
        score = 0
        lines = code.split('\n')

        # Check for proper sorting algorithm patterns
        if 'bubble' in code.lower() or 'insertion' in code.lower() or 'selection' in code.lower():
            # Look for nested loops (typical in sorting)
            nested_loop_count = 0
            for line in lines:
                if 'for (' in line or 'while (' in line:
                    nested_loop_count += 1
            if nested_loop_count >= 2:
                score += 5

        # Check for proper search algorithm patterns
        if 'binary' in code.lower() or 'linear' in code.lower():
            # Look for proper bounds checking
            if 'if (' in code and ('<' in code or '>' in code):
                score += 5

        # Check for recursion patterns
        if 'recursion' in code.lower() or 'recursive' in code.lower():
            # Look for function calls within the same function
            func_calls = re.findall(r'\b\w+\s*\(', code)
            if len(func_calls) > 1:  # More than just main/printf/scanf
                score += 5

        return min(10, score)

    def check_infinite_loops(self, code):
        """Check for potential infinite loop patterns."""
        penalty = 0
        lines = code.split('\n')

        for i, line in enumerate(lines):
            if 'while (' in line:
                # Check if the condition can become false
                condition = line.split('while (')[1].split(')')[0].strip()
                if condition in ['1', 'true', 'TRUE']:
                    penalty += 10  # Likely infinite loop
                elif not any(op in condition for op in ['<', '>', '==', '!=', '&&', '||']):
                    penalty += 5  # Suspicious condition

            elif 'for (' in line:
                # Check for (;;) pattern
                if ';;' in line:
                    penalty += 10  # Infinite for loop

        return penalty

    def check_loop_quality(self, code):
        """Check for proper loop initialization and bounds."""
        score = 0
        lines = code.split('\n')

        for line in lines:
            if 'for (' in line:
                # Check for proper initialization (i = 0)
                if 'i = 0' in line or 'int i = 0' in line:
                    score += 3
                # Check for proper condition (< n or < size)
                if '<' in line and ('n' in line or 'size' in line or 'length' in line):
                    score += 3
                # Check for proper increment (i++)
                if 'i++' in line:
                    score += 3

            elif 'while (' in line:
                # Check for proper condition
                condition = line.split('while (')[1].split(')')[0].strip()
                if any(op in condition for op in ['<', '>', '==', '!=']):
                    score += 5

        return min(15, score)

    def check_variable_logic(self, code):
        """Check for proper variable initialization and usage."""
        score = 0
        lines = code.split('\n')
        variables = set()
        initialized = set()

        # Find variable declarations and initializations
        for line in lines:
            line = line.strip()
            # Variable declarations
            if any(line.startswith(dtype + ' ') for dtype in ['int', 'char', 'float', 'double']):
                var_match = re.findall(r'\b([a-zA-Z_]\w*)\b', line)
                for var in var_match:
                    if var not in ['int', 'char', 'float', 'double', 'void']:
                        variables.add(var)
                        if '=' in line:
                            initialized.add(var)

            # Check for initialization in separate lines
            elif '=' in line and not line.startswith('if') and not line.startswith('while') and not line.startswith('for'):
                var_match = re.findall(r'\b([a-zA-Z_]\w*)\b', line.split('=')[0])
                for var in var_match:
                    if var in variables:
                        initialized.add(var)

        # Check usage before initialization
        for line in lines:
            line = line.strip()
            if 'if (' in line or 'while (' in line or 'for (' in line or 'printf(' in line or 'scanf(' in line:
                used_vars = re.findall(r'\b([a-zA-Z_]\w*)\b', line)
                for var in used_vars:
                    if var in variables and var not in initialized:
                        score -= 3  # Penalize uninitialized usage

        # Bonus for proper initialization
        if len(initialized) > 0:
            score += min(5, len(initialized))

        return max(-10, min(10, score))

    def check_enhanced_logical_consistency(self, code):
        """Enhanced check for logical consistency and potential errors."""
        score = 0

        # Check for division by zero with better detection
        if '/' in code:
            lines = code.split('\n')
            for line in lines:
                if '/' in line and 'if (' not in line:
                    # Check for division by variable without protection
                    if re.search(r'/\s*[a-zA-Z_]\w*\s*;', line):
                        # Look for preceding checks
                        var_match = re.search(r'/\s*([a-zA-Z_]\w*)', line)
                        if var_match:
                            var = var_match.group(1)
                            # Check if there's a check for this variable earlier
                            has_check = False
                            for prev_line in lines[:lines.index(line)]:
                                if f'if ({var}' in prev_line or f'if (!{var}' in prev_line:
                                    has_check = True
                                    break
                            if not has_check:
                                score -= 3

        # Check for array bounds with better detection
        if '[' in code:
            array_accesses = re.findall(r'\[[^\]]*\]', code)
            for access in array_accesses:
                if re.search(r'\b\d+\b', access):  # Direct numeric index
                    index = int(re.search(r'\b(\d+)\b', access).group(1))
                    if index < 0:
                        score -= 5
                    elif index > 100:  # Suspiciously large index
                        score -= 2

        # Check for proper return statements in functions
        func_lines = [line for line in code.split('\n') if line.strip().endswith('{')]
        for i, line in enumerate(func_lines):
            if any(dtype in line for dtype in ['int ', 'float ', 'double ', 'char ']) and 'main' not in line:
                # Non-void function should have return
                brace_count = 0
                has_return = False
                for j in range(i+1, len(code.split('\n'))):
                    next_line = code.split('\n')[j].strip()
                    brace_count += next_line.count('{') - next_line.count('}')
                    if 'return ' in next_line:
                        has_return = True
                    if brace_count == 0:
                        break
                if not has_return:
                    score -= 5

        # Check for logical operator consistency
        if '&&' in code or '||' in code:
            # Look for potential logical errors
            if 'if (a && b || c)' in code:  # Missing parentheses
                score -= 3

        return max(-15, min(15, score))

    def check_operator_usage(self, code):
        """Check for proper operator usage."""
        score = 0

        # Check for assignment vs comparison
        if '=' in code:
            lines = code.split('\n')
            for line in lines:
                if 'if (' in line and '=' in line and '==' not in line:
                    # Potential assignment in condition
                    score -= 3

        # Check for proper increment/decrement usage
        if '++' in code or '--' in code:
            score += 2  # Bonus for using increment/decrement

        # Check for mixed operators
        arith_ops = code.count('+') + code.count('-') + code.count('*') + code.count('/')
        comp_ops = code.count('==') + code.count('!=') + code.count('<') + code.count('>') + code.count('<=') + code.count('>=')
        logic_ops = code.count('&&') + code.count('||')

        if arith_ops > 0 and comp_ops > 0:
            score += 3  # Good mix of arithmetic and comparison

        if logic_ops > 0:
            score += 2  # Uses logical operators

        return max(-5, min(10, score))

    def check_memory_safety(self, code):
        """Check for memory safety issues."""
        score = 0

        # Check for proper malloc/free usage
        if 'malloc' in code:
            malloc_count = code.count('malloc(')
            free_count = code.count('free(')
            if free_count >= malloc_count:
                score += 5  # Proper memory management
            else:
                score -= 5  # Potential memory leaks

        # Check for NULL checks before pointer usage
        if '*' in code:
            pointer_usage = code.count('*')
            null_checks = code.count('NULL') + code.count('null')
            if null_checks > 0:
                score += min(5, null_checks * 2)
            else:
                score -= 3  # No NULL checks with pointers

        # Check for array bounds safety
        if '[' in code:
            array_accesses = re.findall(r'\[[^\]]*\]', code)
            bounds_checks = 0
            for access in array_accesses:
                # Look for bounds checking before array access
                if 'if (' in code and ('<' in code or '>' in code):
                    bounds_checks += 1
            if bounds_checks > 0:
                score += min(5, bounds_checks)

        return max(-10, min(10, score))

    def analyze_c_code_detailed_feedback(self, code, requirements=None):
        """Provide detailed feedback on C code analysis."""
        feedback_parts = []

        # Analyze code length based on activity requirements
        lines = [line for line in code.split('\n') if line.strip()]
        code_length = len(lines)

        # Determine expected code length based on requirements
        if requirements:
            required_features = sum(1 for req in requirements.values() if req is True)
            # Estimate expected length: basic program ~8-15 lines, complex ~20-50 lines
            if required_features <= 3:
                min_expected = 8
                max_expected = 20
            elif required_features <= 7:
                min_expected = 12
                max_expected = 40
            else:
                min_expected = 15
                max_expected = 60
        else:
            # Default thresholds if no requirements provided - more strict for short code
            min_expected = 8
            max_expected = 70

        if code_length < 5:
            feedback_parts.append("Code is extremely short - this appears to be incomplete or missing key functionality")
        elif code_length < min_expected:
            if requirements and required_features > 3:
                feedback_parts.append(f"Code is quite short for the activity requirements - consider implementing more features as specified")
            else:
                feedback_parts.append("Code is quite short - consider adding more functionality")
        elif code_length > max_expected:
            feedback_parts.append("Code is lengthy - consider breaking into functions for better organization")
        else:
            feedback_parts.append("Code length is appropriate for the activity")

        # Requirement analysis disabled

        # Check for potential issues
        issues = []
        if code.count('{') != code.count('}'): issues.append("Brace mismatch detected")
        if 'return 0;' not in code and 'return ' in code: issues.append("Consider returning 0 from main")
        if len([line for line in lines if len(line) > 80]) > 0: issues.append("Some lines are very long")

        if issues:
            feedback_parts.append("Areas for improvement: " + ", ".join(issues))

        return ". ".join(feedback_parts) if feedback_parts else "Code structure analysis complete."

    def extract_activity_requirements(self, activity_text):
        """Extract programming requirements from activity content with semantic context."""
        requirements = {
            'if_else': {'required': False, 'semantic': None},
            'loops': {'required': False, 'semantic': None},
            'functions': {'required': False, 'semantic': None},
            'arrays': {'required': False, 'semantic': None},
            'pointers': {'required': False, 'semantic': None},
            'switch': {'required': False, 'semantic': None},
            'input_output': {'required': False, 'semantic': None},
            'variables': {'required': False, 'semantic': None},
            'comments': {'required': False, 'semantic': None},
            'return_statement': {'required': False, 'semantic': None},
            'main_function': {'required': False, 'semantic': None},
            'include_stdio': {'required': False, 'semantic': None},
            'arithmetic': {'required': False, 'semantic': None},
            'comparison': {'required': False, 'semantic': None},
            'logical_operators': {'required': False, 'semantic': None},
            'specific_content': []
        }

        # Common programming keywords to exclude from specific content
        programming_keywords = {
            'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'break', 'continue',
            'int', 'char', 'float', 'double', 'void', 'return', 'main', 'include',
            'stdio', 'printf', 'scanf', 'function', 'variable', 'array', 'loop',
            'conditional', 'condition', 'input', 'output', 'print', 'read', 'arithmetic',
            'math', 'calculation', 'compare', 'comparison', 'greater', 'less', 'equal',
            'logical', 'operator', 'boolean', 'pointer', 'memory', 'malloc', 'free',
            'comment', 'header', 'library', 'data', 'type', 'declare', 'iteration',
            'define', 'create', 'list', 'matrix', 'and', 'or', 'not'
        }

        # Extract specific content keywords (words not in programming_keywords)
        words = re.findall(r'\b\w+\b', activity_text)
        specific_content = [word for word in words if word not in programming_keywords and len(word) > 2]
        requirements['specific_content'] = list(set(specific_content))  # Remove duplicates

        # Enhanced requirement detection with semantic context
        text_lower = activity_text.lower()

        # If-else requirements with semantic context
        if any(phrase in text_lower for phrase in ['use if-else', 'implement if-else', 'write if-else', 'if-else statement', 'conditional statements', 'decision making']):
            requirements['if_else']['required'] = True
            # Extract semantic context for if-else
            if 'odd' in text_lower and 'even' in text_lower:
                requirements['if_else']['semantic'] = 'odd_even_check'
            elif 'positive' in text_lower and 'negative' in text_lower:
                requirements['if_else']['semantic'] = 'positive_negative_check'
            elif 'grade' in text_lower or 'score' in text_lower:
                requirements['if_else']['semantic'] = 'grade_classification'
            elif 'age' in text_lower:
                requirements['if_else']['semantic'] = 'age_check'

        # Loop requirements with semantic context
        if any(phrase in text_lower for phrase in ['use loops', 'implement loops', 'write loops', 'for loop', 'while loop', 'do-while loop', 'iteration']):
            requirements['loops']['required'] = True
            # Extract semantic context for loops
            if 'array' in text_lower or 'list' in text_lower:
                requirements['loops']['semantic'] = 'array_iteration'
            elif 'sum' in text_lower or 'total' in text_lower:
                requirements['loops']['semantic'] = 'summation'
            elif 'count' in text_lower:
                requirements['loops']['semantic'] = 'counting'
            elif 'print' in text_lower and 'numbers' in text_lower:
                requirements['loops']['semantic'] = 'number_printing'

        # Function requirements
        if any(phrase in text_lower for phrase in ['define a function', 'create a function', 'implement a function', 'write a function', 'user-defined function']):
            requirements['functions']['required'] = True

        # Array requirements with semantic context
        if any(phrase in text_lower for phrase in ['use arrays', 'implement arrays', 'work with arrays', 'array operations']):
            requirements['arrays']['required'] = True
            if 'sort' in text_lower:
                requirements['arrays']['semantic'] = 'array_sorting'
            elif 'search' in text_lower:
                requirements['arrays']['semantic'] = 'array_search'

        # Pointer requirements
        if any(phrase in text_lower for phrase in ['use pointers', 'implement pointers', 'work with pointers', 'pointer operations']):
            requirements['pointers']['required'] = True

        # Switch requirements
        if any(phrase in text_lower for phrase in ['use switch', 'implement switch', 'switch statement', 'switch-case']):
            requirements['switch']['required'] = True

        # Input/Output requirements
        if any(phrase in text_lower for phrase in ['input and output', 'read and write', 'scanf and printf', 'user input', 'display output']):
            requirements['input_output']['required'] = True

        # Variable requirements
        if any(phrase in text_lower for phrase in ['declare variables', 'use variables', 'variable declaration']):
            requirements['variables']['required'] = True

        # Comment requirements
        if any(phrase in text_lower for phrase in ['add comments', 'include comments', 'write comments', 'comment your code']):
            requirements['comments']['required'] = True

        # Return statement requirements
        if any(phrase in text_lower for phrase in ['return statement', 'return value', 'return from function']):
            requirements['return_statement']['required'] = True

        # Main function requirements
        if any(phrase in text_lower for phrase in ['main function', 'int main', 'write main function']):
            requirements['main_function']['required'] = True

        # Include stdio requirements
        if any(phrase in text_lower for phrase in ['include stdio.h', 'include header', 'standard library']):
            requirements['include_stdio']['required'] = True

        # Arithmetic requirements
        if any(phrase in text_lower for phrase in ['arithmetic operators', 'mathematical operations', 'calculations']):
            requirements['arithmetic']['required'] = True

        # Comparison requirements
        if any(phrase in text_lower for phrase in ['comparison operators', 'relational operators', 'compare values']):
            requirements['comparison']['required'] = True

        # Logical operators requirements
        if any(phrase in text_lower for phrase in ['logical operators', 'boolean operators', '&& || !']):
            requirements['logical_operators']['required'] = True

        return requirements

    def check_if_else(self, code):
        if_count = code.count('if ') + code.count('else if') + code.count('else')
        return if_count > 0, if_count, f"if-else statements ({if_count} found)"

    def check_input_output(self, code):
        io_count = code.count('printf(') + code.count('scanf(')
        return io_count > 0, io_count, f"input/output operations ({io_count} found)"

    def check_variables(self, code):
        var_count = len([line for line in code.split('\n') if any(t in line for t in ['int ', 'char ', 'float ', 'double '])])
        return var_count > 0, var_count, f"variable declarations ({var_count} found)"

    def check_main_function(self, code):
        has_main = 'int main(' in code
        return has_main, 1 if has_main else 0, "main function"

    def check_include_stdio(self, code):
        has_stdio = '#include <stdio.h>' in code
        return has_stdio, 1 if has_stdio else 0, "stdio.h include"

    def check_return_statement(self, code):
        has_return = 'return ' in code
        return has_return, 1 if has_return else 0, "return statement"

    def check_logical_operators(self, code):
        logic_count = code.count('&&') + code.count('||') + code.count('!')
        return logic_count > 0, logic_count, f"logical operators ({logic_count} found)"

    def check_loops(self, code):
        loop_count = code.count('for ') + code.count('while ') + code.count('do ')
        return loop_count > 0, loop_count, f"loops ({loop_count} found)"

    def check_functions(self, code):
        func_count = code.count('(') - code.count('main(') - code.count('printf(') - code.count('scanf(')
        return func_count > 0, func_count, f"functions ({func_count} found)"

    def check_arrays(self, code):
        array_count = code.count('[') + code.count(']')
        return array_count > 0, array_count, f"arrays ({array_count} found)"

    def check_pointers(self, code):
        pointer_count = code.count('*') + code.count('&')
        return pointer_count > 0, pointer_count, f"pointers ({pointer_count} found)"

    def check_switch(self, code):
        switch_count = code.count('switch ')
        return switch_count > 0, switch_count, f"switch statements ({switch_count} found)"

    def check_comments(self, code):
        comment_count = code.count('//') + code.count('/*')
        return comment_count > 0, comment_count, f"comments ({comment_count} found)"

    def check_arithmetic(self, code):
        arith_count = code.count('+') + code.count('-') + code.count('*') + code.count('/') + code.count('%')
        return arith_count > 0, arith_count, f"arithmetic operators ({arith_count} found)"

    def check_comparison(self, code):
        comp_count = code.count('==') + code.count('!=') + code.count('<') + code.count('>') + code.count('<=') + code.count('>=')
        return comp_count > 0, comp_count, f"comparison operators ({comp_count} found)"

    def check_specific_content(self, code, keywords):
        code_lower = code.lower()
        found_keywords = [kw for kw in keywords if kw in code_lower]
        return len(found_keywords) > 0, len(found_keywords), f"specific content keywords: {', '.join(found_keywords)}"

    def check_activity_requirements(self, code, requirements):
        """Check if the submitted code meets the specific activity requirements."""
        met_points = 0
        total_required_points = 0
        missing_requirements = []
        met_requirements = []

        # Define points for each requirement
        points_map = {
            'if_else': 15,
            'input_output': 10,
            'variables': 10,
            'main_function': 10,
            'include_stdio': 5,
            'return_statement': 8,
            'logical_operators': 5, 
            'loops': 10,
            'functions': 10,
            'arrays': 10,
            'pointers': 10,
            'switch': 10,
            'comments': 5,
            'arithmetic': 5,
            'comparison': 5,
            'specific_content': 5
        }

        # Define checkers for each requirement
        checkers = {
            'if_else': self.check_if_else,
            'input_output': self.check_input_output,
            'variables': self.check_variables,
            'main_function': self.check_main_function,
            'include_stdio': self.check_include_stdio,
            'return_statement': self.check_return_statement,
            'logical_operators': self.check_logical_operators,
            'loops': self.check_loops,
            'functions': self.check_functions,
            'arrays': self.check_arrays,
            'pointers': self.check_pointers,
            'switch': self.check_switch,
            'comments': self.check_comments,
            'arithmetic': self.check_arithmetic,
            'comparison': self.check_comparison,
            'specific_content': lambda code: self.check_specific_content(code, requirements['specific_content'])
        }

        # First, check explicitly required elements from activity description
        for req_name, req_value in requirements.items():
            # Skip if this requirement is not actually required or if it's the specific_content list
            if req_name == 'specific_content':
                # For specific_content, check if there are actual keywords to look for
                if not requirements['specific_content']:
                    continue
            elif not req_value.get('required', False):
                continue

            total_required_points += points_map[req_name]

            if req_name == 'specific_content':
                met, count, feedback_str = checkers[req_name](code)
            else:
                met, count, feedback_str = checkers[req_name](code)

            if met:
                met_requirements.append(feedback_str)
                met_points += points_map[req_name]
            else:
                missing_requirements.append(req_name.replace('_', ' '))

        # Only check explicitly required elements from activity description
        # Basic programming elements are not automatically required unless mentioned

        # Calculate requirement score as percentage of met requirements
        if total_required_points > 0:
            requirement_score = (met_points / total_required_points) * 100
        else:
            requirement_score = 100  # No requirements detected, no penalty

        # Generate feedback - FIXED: Only show missing requirements if there are actually any
        feedback_parts = []
        
        # Only show missing requirements if there are any
        if missing_requirements:
            feedback_parts.append(f"Missing required elements: {', '.join(missing_requirements)}")
        
        # Only show met requirements if there are any
        if met_requirements:
            feedback_parts.append(f"Successfully implemented: {', '.join(met_requirements)}")
        
        # If nothing was found at all
        if not missing_requirements and not met_requirements:
            feedback_parts.append("No specific requirements detected in activity description")

        return max(0, requirement_score), '. '.join(feedback_parts)

    def normalize_code(self, code):
        """Normalize code while preserving logical structure and algorithm differences."""
        # Remove single-line comments
        code = re.sub(r'//.*', '', code)
        # Remove multi-line comments
        code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
        
        # Remove preprocessor directives but keep includes for structure
        code = re.sub(r'#\s*(define|ifdef|ifndef|endif|pragma).*', '', code)
        
        # Normalize whitespace but preserve basic structure
        lines = code.split('\n')
        normalized_lines = []
        for line in lines:
            line = re.sub(r'\s+', ' ', line.strip())
            if line and not line.startswith('# '):  # Keep includes for structure
                normalized_lines.append(line)
        code = '\n'.join(normalized_lines)
        
        # Replace string literals but keep their presence
        code = re.sub(r'"[^"]*"', 'STR_LITERAL', code)
        
        # Replace character literals
        code = re.sub(r"'[^']'", 'CHAR_LITERAL', code)
        
        # Replace numeric literals but keep their type (int vs float)
        def replace_numeric(match):
            num = match.group(0)
            if '.' in num:
                return 'FLOAT_LITERAL'
            else:
                return 'INT_LITERAL'
        code = re.sub(r'\b\d+\.?\d*\b', replace_numeric, code)
        
        # C keywords and common library functions to preserve
        c_keywords = {
            'auto', 'break', 'case', 'char', 'const', 'continue', 'default', 'do', 
            'double', 'else', 'enum', 'extern', 'float', 'for', 'goto', 'if', 'int', 
            'long', 'register', 'return', 'short', 'signed', 'sizeof', 'static',
            'struct', 'switch', 'typedef', 'union', 'unsigned', 'void', 'volatile', 'while'
        }
        
        # Algorithm-specific functions to PRESERVE (don't replace with VAR)
        algorithm_functions = {
            'sort', 'search', 'bubble', 'insertion', 'selection', 'merge', 'quick', 'heap',
            'binary', 'linear', 'recursive', 'fibonacci', 'factorial', 'prime', 'gcd',
            'reverse', 'palindrome', 'matrix', 'transpose', 'determinant'
        }
        
        library_functions = {
            'printf', 'scanf', 'main', 'malloc', 'free', 'strlen', 'strcpy', 'strcmp', 
            'fopen', 'fclose', 'fprintf', 'fscanf', 'sprintf', 'sscanf', 'gets', 'puts', 
            'getchar', 'putchar', 'atoi', 'atof', 'rand', 'srand', 'time', 'exit', 'abs', 
            'sqrt', 'pow', 'sin', 'cos', 'tan', 'log', 'exp', 'ceil', 'floor'
        }
        
        # PRESERVE control flow patterns and algorithm structure
        control_flow_patterns = [
            (r'for\s*\(\s*[^;]*;\s*[^;]*;\s*[^)]*\)', 'FOR_LOOP'),
            (r'while\s*\(\s*[^)]*\)', 'WHILE_LOOP'),
            (r'do\s*\{', 'DO_LOOP'),
            (r'switch\s*\(\s*[^)]*\)', 'SWITCH_STMT'),
            (r'if\s*\(\s*[^)]*\)', 'IF_STMT'),
            (r'else\s*if\s*\(\s*[^)]*\)', 'ELSE_IF_STMT'),
        ]
        
        # Apply control flow pattern preservation
        for pattern, replacement in control_flow_patterns:
            code = re.sub(pattern, replacement, code, flags=re.IGNORECASE)
        
        # Find all words in the code
        words = set(re.findall(r'\b\w+\b', code))
        
        # Replace user-defined identifiers with VAR, but PRESERVE:
        # 1. Standard library functions
        # 2. Algorithm-related function names  
        # 3. Control flow keywords (already handled above)
        normalized = code
        for word in words:
            if (word not in c_keywords and 
                word not in library_functions and 
                word not in algorithm_functions and
                word not in ['STR_LITERAL', 'CHAR_LITERAL', 'INT_LITERAL', 'FLOAT_LITERAL',
                            'FOR_LOOP', 'WHILE_LOOP', 'DO_LOOP', 'SWITCH_STMT', 'IF_STMT', 'ELSE_IF_STMT']):
                normalized = re.sub(r'\b' + re.escape(word) + r'\b', 'VAR', normalized)
        
        return normalized

    def check_similarity(self, activity_id, code, student_id):
        """Check similarity with other submissions using sequence matching, accounting for variable renaming."""
        try:
            if not code or not isinstance(code, str) or len(code.strip()) == 0:
                return 100, "No valid code submitted for similarity check."

            # Database query with error handling
            try:
                cur = mysql.connection.cursor(cursorclass=MySQLdb.cursors.DictCursor)
                cur.execute("""
                    SELECT code FROM submissions
                    WHERE activity_id = %s AND code IS NOT NULL AND LENGTH(code) > 10
                    AND student_id != %s
                """, (activity_id, student_id))
                submissions = cur.fetchall()
                cur.close()
            except Exception as e:
                logger.error(f"Database error in similarity check: {str(e)}")
                return 100, "Database error during similarity check."

            if len(submissions) == 0:
                return 100, "Insufficient submissions for similarity check."

            other_codes = [row['code'] for row in submissions if row['code'] and isinstance(row['code'], str)]

            if not other_codes:
                return 100, "No similar submissions found."

            # Normalize codes to handle variable renaming
            try:
                normalized_code = self.normalize_code(code)
                if not normalized_code or not normalized_code.strip():
                    return 100, "Submitted code has no meaningful content after normalization."
            except Exception as e:
                logger.error(f"Failed to normalize submitted code: {str(e)}")
                return 100, "Failed to process submitted code for similarity check."

            normalized_other_codes = []
            for other_code in other_codes:
                try:
                    normalized = self.normalize_code(other_code)
                    if normalized and normalized.strip():
                        normalized_other_codes.append(normalized)
                except Exception as e:
                    logger.warning(f"Failed to normalize other code: {str(e)}")
                    continue

            if not normalized_other_codes:
                return 100, "No valid other submissions for similarity check."

            # Use sequence matching for similarity detection
            try:
                max_similarity = 0
                for other_normalized in normalized_other_codes:
                    ratio = SequenceMatcher(None, normalized_code, other_normalized).ratio()
                    if ratio > max_similarity:
                        max_similarity = ratio
            except Exception as e:
                logger.error(f"Error calculating similarity ratio: {str(e)}")
                return 100, "Similarity calculation failed due to technical error."

            max_sim_percent = max_similarity * 100
            score = max(0, 100 - max_sim_percent)
            
            # HIGHER thresholds to avoid false positives for similar structures
            if max_sim_percent > 90: similarity_level = "very high"
            elif max_sim_percent > 75: similarity_level = "high" 
            elif max_sim_percent > 60: similarity_level = "moderate"
            elif max_sim_percent > 40: similarity_level = "low"
            else: similarity_level = "very low"
            
            # Only flag concerning levels
            if max_sim_percent > 75:
                feedback = f"⚠️ High similarity detected with other submissions: {similarity_level} ({max_sim_percent:.1f}%). Please ensure this is your own work."
            else:
                feedback = f"Similarity with other submissions: {similarity_level} ({max_sim_percent:.1f}%)."

            return score, feedback

        except Exception as e:
            logger.error(f"Similarity check failed: {str(e)}")
            return 100, "Similarity check unavailable due to technical error."

    def train_ml_grading_model(self):
        """Train machine learning models using historical grading data."""
        try:
            logger.info("Starting ML model training...")

            # Get historical graded submissions
            cur = mysql.connection.cursor(cursorclass=MySQLdb.cursors.DictCursor)
            cur.execute("""
                SELECT code, correctness_score, syntax_score, logic_score
                FROM submissions
                WHERE code IS NOT NULL
                AND LENGTH(code) > 20
                AND correctness_score IS NOT NULL
                AND syntax_score IS NOT NULL
                AND logic_score IS NOT NULL
                ORDER BY submitted_at DESC
                LIMIT 1000
            """)
            training_data = cur.fetchall()
            cur.close()

            if len(training_data) < 50:
                logger.warning(f"Insufficient training data: {len(training_data)} submissions found. Need at least 50.")
                return False

            logger.info(f"Found {len(training_data)} submissions for training")

            # Prepare training data
            codes = []
            correctness_scores = []
            syntax_scores = []
            logic_scores = []

            for row in training_data:
                code, correctness, syntax, logic = row
                codes.append(code)
                correctness_scores.append(correctness)
                syntax_scores.append(syntax)
                logic_scores.append(logic)

            # Extract features from all codes
            logger.info("Extracting features from training data...")
            feature_vectors = []
            for code in codes:
                features = self.extract_code_features(code)
                feature_vectors.append(list(features.values()))

            # Convert to numpy arrays
            X = np.array(feature_vectors)
            y_correctness = np.array(correctness_scores)
            y_syntax = np.array(syntax_scores)
            y_logic = np.array(logic_scores)

            # Scale features
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)

            # Train models
            logger.info("Training ML models...")

            correctness_model = RandomForestRegressor(n_estimators=100, random_state=42)
            correctness_model.fit(X_scaled, y_correctness)

            logic_model = RandomForestRegressor(n_estimators=100, random_state=42)
            logic_model.fit(X_scaled, y_logic)

            syntax_model = RandomForestRegressor(n_estimators=100, random_state=42)
            syntax_model.fit(X_scaled, y_syntax)

            # Save models
            ml_models = {
                'correctness_model': correctness_model,
                'logic_model': logic_model,
                'syntax_model': syntax_model,
                'scaler': scaler,
                'feature_names': list(self.extract_code_features(codes[0]).keys()),
                'training_samples': len(training_data),
                'trained_at': str(os.path.getctime(__file__)) if os.path.exists(__file__) else 'unknown'
            }

            with open('ml_grading_models.pkl', 'wb') as f:
                pickle.dump(ml_models, f)

            logger.info(f"ML models trained and saved successfully with {len(training_data)} samples")
            return True

        except Exception as e:
            logger.error(f"Error training ML models: {str(e)}")
            return False


# Create a global instance of the grader
code_grader = CodeGrader()

# For backward compatibility
def grade_submission(activity_id, student_id, code):
    return code_grader.grade_submission(activity_id, student_id, code)

def check_syntax(code):
    return code_grader.check_syntax(code)

def train_ml_grading_model():
    return code_grader.train_ml_grading_model()
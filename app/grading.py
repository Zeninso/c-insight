import subprocess
import tempfile
import os
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
import numpy as np
import pickle
import logging
import hashlib
from app import mysql

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CodeGrader:
    def __init__(self):
        self.ml_models = None
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

    def grade_submission(self, activity_id, student_id, code):
        """
        Grade a student submission based on the activity's rubric.
        """
        try:
            # Get activity details
            cur = mysql.connection.cursor()
            cur.execute("""
                SELECT title, description, instructions, starter_code, 
                       correctness_weight, syntax_weight, logic_weight, similarity_weight
                FROM activities WHERE id = %s
            """, (activity_id,))
            activity = cur.fetchone()
            cur.close()

            if not activity:
                return {'error': 'Activity not found'}

            title, description, instructions, starter_code, correctness_w, syntax_w, logic_w, similarity_w = activity

            # Extract requirements from activity content
            activity_text = f"{title or ''} {description or ''} {instructions or ''}".lower()
            requirements = self.extract_activity_requirements(activity_text)

            # Check if code meets specific activity requirements
            requirement_score, requirement_feedback = self.check_activity_requirements(code, requirements)
            
            # Syntax check using GCC
            syntax_score, syntax_feedback = self.check_syntax(code)
            
            # Correctness and Logic analysis
            correctness_score, logic_score, ast_feedback = self.check_ast_with_requirements(
                code, requirements, requirement_score
            )
            
            # Similarity check - only if syntax is correct
            if syntax_score >= 50:
                similarity_score, sim_feedback = self.check_similarity(activity_id, code, student_id)
            else:
                similarity_score, sim_feedback = 100, "Skipped similarity check due to syntax errors"

            # Calculate weighted scores
            total_score = (
                (correctness_score * correctness_w / 100) +
                (syntax_score * syntax_w / 100) +
                (logic_score * logic_w / 100) +
                (similarity_score * similarity_w / 100)
            ) * (requirement_score / 100)

            # Compile feedback
            feedback_parts = [
                f"Requirement Analysis: {requirement_feedback}",
                f"Syntax Check: {syntax_feedback}",
                f"Code Analysis: {ast_feedback}",
                f"Similarity Check: {sim_feedback}"
            ]

            return {
                'correctness_score': int(correctness_score),
                'syntax_score': int(syntax_score),
                'logic_score': int(logic_score),
                'similarity_score': int(similarity_score),
                'requirement_score': int(requirement_score),
                'total_score': int(total_score),
                'feedback': ' '.join(feedback_parts)
            }

        except Exception as e:
            logger.error(f"Error grading submission: {str(e)}")
            return {'error': f'Grading failed: {str(e)}'}

    def check_syntax(self, code):
        """Check syntax using GCC compiler for C code."""
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.c', delete=False) as f:
                f.write(code)
                temp_file = f.name

            # Compile with GCC
            result = subprocess.run(
                ['gcc', '-fsyntax-only', temp_file],
                capture_output=True, text=True, timeout=10
            )

            os.unlink(temp_file)

            if result.returncode == 0:
                return 100, "Syntax is correct."
            else:
                errors = result.stderr.strip()
                error_count = len(re.findall(r'error:', errors))
                
                if error_count == 0:
                    return 90, "Minor syntax issues found."
                elif error_count == 1:
                    return 70, f"One syntax error found: {errors[:200]}..."
                elif error_count <= 3:
                    return 50, f"Few syntax errors found: {errors[:200]}..."
                else:
                    return 20, f"Multiple syntax errors: {errors[:200]}..."

        except subprocess.TimeoutExpired:
            return 0, "Syntax check timed out."
        except Exception as e:
            return 0, f"Syntax check failed: {str(e)}"

    def check_ast_with_requirements(self, code, requirements, requirement_score):
        """Check correctness and logic using analysis, adjusted for requirements."""
        correctness_score, logic_score, syntax_score, enhanced_feedback = self.enhanced_ml_grading(code)

        feedback_parts = [
            "Advanced C Code Analysis",
            f"Code Correctness: {correctness_score:.1f}%",
            f"Logic Quality: {logic_score:.1f}%"
        ]

        # Adjust scores based on requirements
        if requirement_score < 70:
            if requirements['if_else'] and (code.count('if ') + code.count('else if') + code.count('else')) == 0:
                correctness_score = max(0, correctness_score * 0.7)
                logic_score = max(0, logic_score * 0.7)
                feedback_parts.append("Penalty: Missing required if-else logic.")

        feedback_parts.append(enhanced_feedback)

        return correctness_score, logic_score, '. '.join(feedback_parts)

    def enhanced_ml_grading(self, code):
        """Enhanced grading function combining ML predictions with rule-based analysis."""
        if self.ml_models:
            ml_correctness, ml_logic, ml_syntax, analysis_type = self.predict_grading_scores(code)
        else:
            ml_correctness, ml_logic, ml_syntax, analysis_type = 0, 0, 0, "Rule-based analysis"

        # Get rule-based analysis
        rule_correctness = self.analyze_c_code_correctness(code)
        rule_logic = self.analyze_c_code_logic(code)
        rule_syntax, _ = self.check_syntax(code)

        # Combine scores
        if analysis_type == "ML-enhanced analysis":
            final_correctness = 0.7 * ml_correctness + 0.3 * rule_correctness
            final_logic = 0.7 * ml_logic + 0.3 * rule_logic
            final_syntax = 0.6 * ml_syntax + 0.4 * rule_syntax
        else:
            final_correctness = rule_correctness
            final_logic = rule_logic
            final_syntax = rule_syntax

        return final_correctness, final_logic, final_syntax, self.analyze_c_code_detailed_feedback(code)

    def predict_grading_scores(self, code):
        """Use trained ML models to predict grading scores."""
        if not self.ml_models:
            correctness_score = self.analyze_c_code_correctness(code)
            logic_score = self.analyze_c_code_logic(code)
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
            logic_score = self.analyze_c_code_logic(code)
            syntax_score = self.check_syntax(code)[0]
            return correctness_score, logic_score, syntax_score, "Rule-based analysis"

    def extract_code_features(self, code):
        """Extract features from C code for machine learning analysis."""
        lines = code.split('\n')
        code_lines = [line.strip() for line in lines if line.strip()]
        
        features = {
            'total_lines': len(code_lines),
            'code_length': len(code),
            'variable_declarations': len([line for line in code_lines if any(t in line for t in ['int ', 'char ', 'float ', 'double '])]),
            'function_calls': code.count('(') - code.count('main('),
            'return_statements': code.count('return '),
            'semicolon_count': code.count(';'),
            'brace_balance': abs(code.count('{') - code.count('}')),
            'if_statements': code.count('if ') + code.count('else if'),
            'loop_statements': code.count('for ') + code.count('while ') + code.count('do '),
            'switch_statements': code.count('switch '),
            'pointer_operations': code.count('*') + code.count('&'),
            'memory_functions': code.count('malloc') + code.count('free') + code.count('calloc') + code.count('realloc'),
            'array_operations': code.count('[') + code.count(']'),
            'include_statements': code.count('#include'),
            'stdio_usage': 1 if '#include <stdio.h>' in code else 0,
            'printf_calls': code.count('printf('),
            'scanf_calls': code.count('scanf('),
            'comment_lines': code.count('//') + code.count('/*'),
            'logical_operators': code.count('&&') + code.count('||'),
            'comparison_operators': code.count('==') + code.count('!=') + code.count('<') + code.count('>') + code.count('<=') + code.count('>='),
            'arithmetic_operators': code.count('+') + code.count('-') + code.count('*') + code.count('/') + code.count('%'),
            'null_checks': code.count('NULL') + code.count('null'),
        }
        
        # Calculate derived features
        features['total_control_flow'] = features['if_statements'] + features['loop_statements'] + features['switch_statements']
        features['nested_loops'] = max(0, features['loop_statements'] - 1)
        features['function_complexity'] = features['total_control_flow'] / max(1, features['function_calls'])
        features['avg_line_length'] = np.mean([len(line) for line in code_lines]) if code_lines else 0
        
        return features

    def analyze_c_code_correctness(self, code):
        """Analyze C code correctness based on specific criteria."""
        score = 50  # Base score

        # Variable Declaration and Usage
        var_declarations = len([line for line in code.split('\n') if any(t in line for t in ['int ', 'char ', 'float ', 'double '])])
        score += 15 if var_declarations > 0 else -10

        # Function Structure
        func_count = code.count('(') - code.count('main(')
        score += 15 if func_count > 0 else -10

        # Return Statements
        return_count = code.count('return ')
        score += 10 if return_count > 0 else -5

        # Semicolon Usage
        lines = code.split('\n')
        total_lines = len([line for line in lines if line.strip()])
        semicolon_lines = len([line for line in lines if line.strip().endswith(';')])
        if total_lines > 0:
            score += int((semicolon_lines / total_lines) * 15)

        # Code Organization
        indented_lines = len([line for line in lines if line.startswith('    ') or line.startswith('\t')])
        if total_lines > 0:
            score += int((indented_lines / total_lines) * 15)

        # Memory Management
        pointer_usage = code.count('*') + code.count('&') + code.count('malloc') + code.count('free')
        score += 10 if pointer_usage > 0 else 0

        return min(100, max(0, score))

    def analyze_c_code_logic(self, code):
        """Analyze C code logic complexity and flow."""
        score = 50  # Base score

        # Control Flow Complexity
        if_count = code.count('if ') + code.count('else if')
        loop_count = code.count('for ') + code.count('while ') + code.count('do ')
        switch_count = code.count('switch ')
        total_control = if_count + loop_count + switch_count
        
        if total_control > 0:
            score += 20 if total_control <= 5 else 15 if total_control <= 10 else 5
        else:
            score -= 10

        # Algorithm Indicators
        algorithm_indicators = 0
        if 'sort' in code.lower() or 'search' in code.lower():
            algorithm_indicators += 1
        if '%' in code:
            algorithm_indicators += 1
        if 'sqrt' in code or 'pow' in code:
            algorithm_indicators += 1
        if '&&' in code or '||' in code:
            algorithm_indicators += 1

        score += min(20, algorithm_indicators * 5)

        # Data Processing
        array_usage = code.count('[') + code.count(']')
        score += 10 if array_usage > 0 else 0

        # Error Handling
        error_patterns = code.count('NULL') + code.count('if (') + code.count('else')
        score += 10 if error_patterns > 0 else 0

        # Code Efficiency
        nested_loops = code.count('for (') + code.count('while (') - 1
        if nested_loops <= 0:
            score += 15
        elif nested_loops <= 2:
            score += 10
        else:
            score += 5

        return min(100, max(0, score))

    def analyze_c_code_detailed_feedback(self, code):
        """Provide detailed feedback on C code analysis."""
        feedback_parts = []

        # Analyze code length
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
        if 'printf(' in code: patterns_found.append("Uses output functions")
        if 'scanf(' in code: patterns_found.append("Uses input functions")
        if '#include <stdio.h>' in code: patterns_found.append("Includes standard I/O library")
        if 'int main(' in code: patterns_found.append("Has main function")
        if '{' in code and '}' in code: patterns_found.append("Proper code blocks")
        
        if patterns_found:
            feedback_parts.append("Positive patterns: " + ", ".join(patterns_found))

        # Check for potential issues
        issues = []
        if code.count('{') != code.count('}'): issues.append("Brace mismatch detected")
        if 'return 0;' not in code and 'return ' in code: issues.append("Consider returning 0 from main")
        if len([line for line in lines if len(line) > 80]) > 0: issues.append("Some lines are very long")
        
        if issues:
            feedback_parts.append("Areas for improvement: " + ", ".join(issues))

        return ". ".join(feedback_parts) if feedback_parts else "Code structure analysis complete."

    def extract_activity_requirements(self, activity_text):
        """Extract programming requirements from activity content."""
        requirements = {
            'if_else': False, 'loops': False, 'functions': False, 'arrays': False,
            'pointers': False, 'switch': False, 'input_output': False, 'variables': False,
            'comments': False, 'return_statement': False, 'main_function': False,
            'include_stdio': False, 'arithmetic': False, 'comparison': False,
            'logical_operators': False
        }

        # Check for if-else requirements (more specific to avoid false positives)
        if any(keyword in activity_text for keyword in ['if-else', 'conditional', 'condition']):
            requirements['if_else'] = True
        elif 'if ' in activity_text and 'if-else' not in activity_text:
            requirements['if_else'] = True

        # Check for other requirements
        if any(keyword in activity_text for keyword in ['for ', 'while ', 'do ', 'loop', 'iteration']):
            requirements['loops'] = True
        if any(keyword in activity_text for keyword in ['function', 'define a function', 'create a function']):
            requirements['functions'] = True
        if any(keyword in activity_text for keyword in ['array', 'list', 'matrix']):
            requirements['arrays'] = True
        if any(keyword in activity_text for keyword in ['input', 'output', 'print', 'read', 'scanf', 'printf']):
            requirements['input_output'] = True
        if any(keyword in activity_text for keyword in ['variable', 'declare', 'data type']):
            requirements['variables'] = True
        if 'return' in activity_text:
            requirements['return_statement'] = True
        if 'main' in activity_text:
            requirements['main_function'] = True
        if any(keyword in activity_text for keyword in ['include', 'header', 'library']):
            requirements['include_stdio'] = True
        if any(keyword in activity_text for keyword in ['arithmetic', 'math', 'calculation']):
            requirements['arithmetic'] = True
        if any(keyword in activity_text for keyword in ['compare', 'comparison', 'greater', 'less', 'equal']):
            requirements['comparison'] = True
            
        # Only flag logical operators if explicitly mentioned
        if any(keyword in activity_text for keyword in ['logical operator', 'boolean operator', '&&', '||', '!']):
            requirements['logical_operators'] = True

        return requirements

    def check_activity_requirements(self, code, requirements):
        """Check if the submitted code meets the specific activity requirements."""
        score = 100
        missing_requirements = []
        met_requirements = []

        # Define essential requirements for this activity
        essential_reqs = ['if_else', 'input_output', 'variables', 'main_function', 'include_stdio', 'return_statement']
        
        # Check each requirement
        for req_name, req_value in requirements.items():
            if not req_value:
                continue
                
            if req_name == 'if_else':
                if_count = code.count('if ') + code.count('else if') + code.count('else')
                if if_count == 0 and req_name in essential_reqs:
                    score -= 15
                    missing_requirements.append("if-else statements")
                elif if_count > 0:
                    met_requirements.append(f"if-else statements ({if_count} found)")
                    
            elif req_name == 'input_output':
                io_count = code.count('printf(') + code.count('scanf(')
                if io_count == 0 and req_name in essential_reqs:
                    score -= 10
                    missing_requirements.append("input/output operations")
                elif io_count > 0:
                    met_requirements.append(f"input/output operations ({io_count} found)")
                    
            elif req_name == 'variables':
                var_count = len([line for line in code.split('\n') if any(t in line for t in ['int ', 'char ', 'float ', 'double '])])
                if var_count == 0 and req_name in essential_reqs:
                    score -= 10
                    missing_requirements.append("variable declarations")
                elif var_count > 0:
                    met_requirements.append(f"variable declarations ({var_count} found)")
                    
            elif req_name == 'main_function':
                if 'int main(' not in code and req_name in essential_reqs:
                    score -= 10
                    missing_requirements.append("main function")
                else:
                    met_requirements.append("main function")
                    
            elif req_name == 'include_stdio':
                if '#include <stdio.h>' not in code and req_name in essential_reqs:
                    score -= 5
                    missing_requirements.append("stdio.h include")
                else:
                    met_requirements.append("stdio.h include")
                    
            elif req_name == 'return_statement':
                if 'return ' not in code and req_name in essential_reqs:
                    score -= 8
                    missing_requirements.append("return statement")
                else:
                    met_requirements.append("return statement")
                    
            # For non-essential requirements like logical_operators, don't penalize
            elif req_name == 'logical_operators':
                logic_count = code.count('&&') + code.count('||') + code.count('!')
                if logic_count > 0:
                    met_requirements.append(f"logical operators ({logic_count} found)")
                # No penalty if missing since it's not essential

        # Generate feedback
        feedback_parts = []
        if missing_requirements:
            feedback_parts.append(f"Missing required elements: {', '.join(missing_requirements)}.")
        if met_requirements:
            feedback_parts.append(f"Successfully implemented: {', '.join(met_requirements)}.")
        if not missing_requirements and not met_requirements:
            feedback_parts.append("No specific requirements detected in activity description.")

        return max(0, score), ' '.join(feedback_parts)

    def check_similarity(self, activity_id, code, student_id):
        """Check similarity with other submissions using cosine similarity."""
        try:
            cur = mysql.connection.cursor()
            cur.execute("""
                SELECT code FROM submissions
                WHERE activity_id = %s AND code IS NOT NULL AND LENGTH(code) > 10
                AND student_id != %s
            """, (activity_id, student_id))
            submissions = cur.fetchall()
            cur.close()

            if len(submissions) == 0:
                return 100, "Insufficient submissions for similarity check."

            # Use all other submissions for comparison
            other_codes = [row[0] for row in submissions]

            if not other_codes:
                return 100, "No similar submissions found."

            # Add current code for comparison
            all_codes = other_codes + [code]

            # Vectorize using TF-IDF
            vectorizer = TfidfVectorizer(stop_words='english', ngram_range=(1, 3), min_df=2)
            try:
                tfidf_matrix = vectorizer.fit_transform(all_codes)

                # Calculate similarities
                similarities = cosine_similarity(tfidf_matrix[-1:], tfidf_matrix[:-1])[0]

                if len(similarities) > 0:
                    max_sim = np.max(similarities) * 100
                    score = max(0, 100 - max_sim)

                    # Determine similarity level
                    if max_sim > 80: similarity_level = "very high"
                    elif max_sim > 60: similarity_level = "high"
                    elif max_sim > 40: similarity_level = "moderate"
                    elif max_sim > 20: similarity_level = "low"
                    else: similarity_level = "very low"

                    feedback = f"Similarity with other submissions: {similarity_level} ({max_sim:.1f}%)."
                else:
                    score = 100
                    feedback = "No similar submissions found."

            except ValueError:
                score = 100
                feedback = "No similar submissions found."

            return score, feedback

        except Exception as e:
            logger.error(f"Similarity check failed: {str(e)}")
            return 50, f"Similarity check failed: {str(e)}"

    def train_ml_grading_model(self):
        """Train machine learning models using historical grading data."""
        try:
            logger.info("Starting ML model training...")

            # Get historical graded submissions
            cur = mysql.connection.cursor()
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
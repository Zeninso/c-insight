import subprocess
import tempfile
import os
import re
import datetime
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
                SELECT title, description, instructions, starter_code, due_date,
                        correctness_weight, syntax_weight, logic_weight, similarity_weight
                FROM activities WHERE id = %s
            """, (activity_id,))
            activity = cur.fetchone()
            cur.close()

            if not activity:
                return {'error': 'Activity not found'}

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

            # Extract requirements from activity content
            activity_text = f"{title or ''} {description or ''} {instructions or ''}".lower()
            requirements = self.extract_activity_requirements(activity_text)

            # Check if code meets specific activity requirements
            requirement_score, requirement_feedback = self.check_activity_requirements(code, requirements)

            # Syntax check using GCC
            syntax_score, syntax_feedback = self.check_syntax(code)

            # If syntax score is below threshold, assign zero to all scores and skip further checks
            if syntax_score < 85:
                correctness_score = 0
                syntax_score = 0
                logic_score = 0
                similarity_score = 0
                ast_feedback = "Submission has syntax errors; grading scores set to zero."
                sim_feedback = "Similarity check skipped due to syntax errors."
            else:
                # Correctness and Logic analysis
                correctness_score, logic_score, ast_feedback = self.check_ast_with_requirements(
                    code, requirements, requirement_score
                )

                # Apply requirement penalty to correctness score
                correctness_score = correctness_score * (requirement_score / 100)

                # Similarity check
                similarity_score, sim_feedback = self.check_similarity(activity_id, code, student_id)

            # Check for overdue penalty
            overdue_penalty = 0
            if due_date and datetime.datetime.now() > due_date:
                overdue_penalty = 25
                penalty_per = overdue_penalty / 3
                correctness_score = max(0, correctness_score - penalty_per)
                syntax_score = max(0, syntax_score - penalty_per)
                logic_score = max(0, logic_score - penalty_per)

            # Update feedback with final scores after penalty
            ast_feedback = f"Correctness: {correctness_score:.1f}%, Logic: {logic_score:.1f}%, Syntax: {syntax_score:.1f}%. {ast_feedback}"

            # Calculate weighted scores
            total_score = (
                (correctness_score * correctness_w / 100) +
                (syntax_score * syntax_w / 100) +
                (logic_score * logic_w / 100) +
                (similarity_score * similarity_w / 100)
            )

            # Compile feedback
            feedback_parts = [
                f"Requirement Analysis: {requirement_feedback}",
                f"Syntax Check: {syntax_feedback}",
                f"Code Analysis: {ast_feedback}",
                f"Similarity Check: {sim_feedback}"
            ]
            if overdue_penalty > 0:
                feedback_parts.append(f"Overdue Penalty: -{overdue_penalty} points distributed across correctness, syntax, and logic")

            return {
                'correctness_score': int(correctness_score),
                'syntax_score': int(syntax_score),
                'logic_score': int(logic_score),
                'similarity_score': int(similarity_score),
                'requirement_score': int(requirement_score),
                'total_score': int(total_score),
                'feedback': '. '.join(feedback_parts)
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
                return 100, " Your Syntax is correct"
            else:
                errors = result.stderr.strip()
                error_count = len(re.findall(r'error:', errors))

                if error_count == 0:
                    return 80, "Minor syntax issues found"
                elif error_count == 1:
                    return 60, f"One syntax error found: {errors[:200]}..."
                elif error_count <= 3:
                    return 40, f"Few syntax errors found: {errors[:200]}..."
                else:
                    return 15, f"Multiple syntax errors: {errors[:200]}..."

        except subprocess.TimeoutExpired:
            return 0, "Syntax check timed out."
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

    def check_ast_with_requirements(self, code, requirements, requirement_score):
        """Check correctness and logic using analysis."""
        correctness_score, logic_score, syntax_score, enhanced_feedback = self.enhanced_ml_grading(code, requirements)

        return correctness_score, logic_score, enhanced_feedback

    def enhanced_ml_grading(self, code, requirements=None):
        """Enhanced grading function combining ML predictions with rule-based analysis."""
        if self.ml_models:
            ml_correctness, ml_logic, ml_syntax, analysis_type = self.predict_grading_scores(code, requirements)
        else:
            ml_correctness, ml_logic, ml_syntax, analysis_type = 0, 0, 0, "Rule-based analysis"

        # Get rule-based analysis
        rule_correctness = self.analyze_c_code_correctness(code)
        rule_logic = self.analyze_c_code_logic(code, requirements)
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

    def predict_grading_scores(self, code, requirements=None):
        """Use trained ML models to predict grading scores."""
        if not self.ml_models:
            correctness_score = self.analyze_c_code_correctness(code)
            logic_score = self.analyze_c_code_logic(code, requirements)
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
            logic_score = self.analyze_c_code_logic(code, requirements)
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
        score = 50  # Base score

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

    def analyze_c_code_logic(self, code, requirements=None):
        """Analyze C code logic complexity and flow with enhanced criteria."""
        score = 40  # Base score increased for better baseline

        # Control Flow Complexity
        if_count = code.count('if ') + code.count('else if')
        loop_count = code.count('for ') + code.count('while ') + code.count('do ')
        switch_count = code.count('switch ')
        total_control = if_count + loop_count + switch_count

        # Check if control flow is required
        control_flow_required = False
        if requirements:
            control_flow_required = requirements.get('if_else', False) or requirements.get('loops', False) or requirements.get('switch', False)

        if total_control > 0:
            # More generous scoring for control flow complexity
            if total_control <= 3:
                score += 25
            elif total_control <= 7:
                score += 20
            elif total_control <= 12:
                score += 15
            else:
                score += 10
        else:
            # Only penalize for missing control flow if it's explicitly required
            if control_flow_required:
                lines = [line.strip() for line in code.split('\n') if line.strip()]
                if len(lines) > 5:
                    score -= 5  # Penalize larger programs missing required control flow
            else:
                # No penalty if control flow not required
                score += 10

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
        # Additional algorithm patterns
        if 'bubble' in code.lower() or 'insertion' in code.lower() or 'selection' in code.lower():
            algorithm_indicators += 2  # Higher weight for sorting algorithms
        if 'binary' in code.lower() or 'linear' in code.lower():
            algorithm_indicators += 2  # Higher weight for search algorithms
        if 'recursion' in code.lower() or 'recursive' in code.lower():
            algorithm_indicators += 2  # Higher weight for recursion

        score += min(25, algorithm_indicators * 5)  # Increased weight and max

        # Data Processing - only score if arrays are required or used
        array_usage = code.count('[') + code.count(']')
        if requirements and requirements.get('arrays', False):
            score += 15 if array_usage > 0 else -5  # Penalize if arrays required but not used
        elif array_usage > 0:
            score += 15  # Bonus if arrays used even if not required

        # Error Handling (basic check for NULL and conditional usage)
        error_patterns = code.count('NULL') + code.count('if (') + code.count('else')
        score += 15 if error_patterns > 0 else 0  # Increased weight

        # Code Efficiency (nested loops) - only if loops are used
        if loop_count > 0:
            nested_loops = max(0, code.count('for (') + code.count('while (') - 1)
            if nested_loops == 0:
                score += 20
            elif nested_loops <= 2:
                score += 15
            else:
                score += 10

        # Check for use of break/continue for loop control - only if loops are used
        if loop_count > 0 and ('break;' in code or 'continue;' in code):
            score += 10  # Increased weight

        # Additional logic checks for better variation
        # Check for proper loop initialization - only if loops are used
        if loop_count > 0:
            loop_init_patterns = code.count('for (int ') + code.count('for (i =') + code.count('while (')
            score += min(15, loop_init_patterns * 3)  # Increased weight

        # Check for function calls within logic - only if functions are required
        if requirements and requirements.get('functions', False):
            func_in_logic = code.count('if (') + code.count('while (') + code.count('for (')
            if func_in_logic > 0:
                score += min(15, func_in_logic * 2)  # Increased weight
        else:
            # If functions not required, don't penalize for missing function calls in logic
            pass

        # Penalize for missing logic in simple programs - but only if logic features are required
        lines = code.split('\n')
        code_lines = [line.strip() for line in lines if line.strip()]
        if len(code_lines) > 5 and total_control == 0 and control_flow_required:
            score -= 10  # Reduced penalty only if control flow was required

        # Enhanced logic checks
        # Check for proper variable initialization
        var_init_score = self.check_variable_initialization(code)
        score += var_init_score

        # Check for logical consistency (e.g., no obvious errors)
        logic_consistency_score = self.check_logical_consistency(code)
        score += logic_consistency_score

        # Check for proper nesting and structure
        nesting_score = self.check_nesting_structure(code)
        score += nesting_score

        # Check for unreachable code patterns
        unreachable_score = self.check_unreachable_code(code)
        score += unreachable_score

        return min(100, max(0, score))

    def check_variable_initialization(self, code):
        """Check if variables are properly initialized before use."""
        score = 0
        lines = code.split('\n')
        variables = set()
        initialized = set()

        for line in lines:
            line = line.strip()
            # Find variable declarations
            if any(line.startswith(dtype + ' ') for dtype in ['int', 'char', 'float', 'double']):
                # Extract variable names
                var_match = re.findall(r'\b([a-zA-Z_]\w*)\b', line)
                for var in var_match:
                    if var not in ['int', 'char', 'float', 'double', 'void']:
                        variables.add(var)
                        # Check if initialized
                        if '=' in line:
                            initialized.add(var)

        # Check if variables are used before initialization
        for line in lines:
            line = line.strip()
            if 'if (' in line or 'while (' in line or 'for (' in line:
                # Extract variables used in conditions
                used_vars = re.findall(r'\b([a-zA-Z_]\w*)\b', line)
                for var in used_vars:
                    if var in variables and var not in initialized:
                        score -= 5  # Penalize uninitialized variable usage

        return max(-10, min(10, score))  # Cap the score

    def check_logical_consistency(self, code):
        """Check for logical consistency and potential errors."""
        score = 0

        # Check for division by zero patterns
        if '/' in code:
            lines = code.split('\n')
            for line in lines:
                if '/' in line and 'if (' not in line:
                    # Simple check: if dividing by a variable, should have some check
                    if re.search(r'/\s*[a-zA-Z_]\w*', line):
                        score -= 2  # Potential division by zero

        # Check for array bounds (simple check)
        if '[' in code:
            array_accesses = re.findall(r'\[[^\]]*\]', code)
            for access in array_accesses:
                if re.search(r'\b\d+\b', access):  # Direct index
                    index = int(re.search(r'\b(\d+)\b', access).group(1))
                    if index < 0:
                        score -= 5  # Negative index

        # Check for proper return statements in functions
        func_lines = [line for line in code.split('\n') if line.strip().endswith('{')]
        for i, line in enumerate(func_lines):
            if 'int ' in line or 'float ' in line or 'double ' in line or 'char ' in line:
                # Check if there's a return in the function
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
                    score -= 3  # Missing return in non-void function

        return max(-15, min(15, score))  # Cap the score

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

    def analyze_c_code_detailed_feedback(self, code, requirements=None):
        """Provide detailed feedback on C code analysis."""
        feedback_parts = []

        # Analyze code length based on activity requirements
        lines = [line for line in code.split('\n') if line.strip()]
        code_length = len(lines)

        # Determine expected code length based on requirements
        if requirements:
            required_features = sum(1 for req in requirements.values() if req is True)
            # Estimate expected length: basic program ~5-15 lines, complex ~20-50 lines
            if required_features <= 3:
                min_expected = 5
                max_expected = 20
            elif required_features <= 7:
                min_expected = 10
                max_expected = 40
            else:
                min_expected = 15
                max_expected = 60
        else:
            # Default thresholds if no requirements provided
            min_expected = 10
            max_expected = 70

        if code_length < min_expected:
            if requirements and required_features > 3:
                feedback_parts.append(f"Code is quite short for the activity requirements - consider implementing more features as specified")
            else:
                feedback_parts.append("Code is quite short - consider adding more functionality")
        elif code_length > max_expected:
            feedback_parts.append("Code is lengthy - consider breaking into functions for better organization")
        else:
            feedback_parts.append("Code length is appropriate for the activity")

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
            'logical_operators': False, 'specific_content': []
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

        # More precise requirement detection - only set to True if explicitly required
        if any(phrase in activity_text for phrase in ['use if-else', 'implement if-else', 'write if-else', 'if-else statement', 'conditional statements', 'decision making']):
            requirements['if_else'] = True

        if any(phrase in activity_text for phrase in ['use loops', 'implement loops', 'write loops', 'for loop', 'while loop', 'do-while loop', 'iteration']):
            requirements['loops'] = True

        if any(phrase in activity_text for phrase in ['define a function', 'create a function', 'implement a function', 'write a function', 'user-defined function']):
            requirements['functions'] = True

        if any(phrase in activity_text for phrase in ['use arrays', 'implement arrays', 'work with arrays', 'array operations']):
            requirements['arrays'] = True

        if any(phrase in activity_text for phrase in ['use pointers', 'implement pointers', 'work with pointers', 'pointer operations']):
            requirements['pointers'] = True

        if any(phrase in activity_text for phrase in ['use switch', 'implement switch', 'switch statement', 'switch-case']):
            requirements['switch'] = True

        if any(phrase in activity_text for phrase in ['input and output', 'read and write', 'scanf and printf', 'user input', 'display output']):
            requirements['input_output'] = True

        if any(phrase in activity_text for phrase in ['declare variables', 'use variables', 'variable declaration']):
            requirements['variables'] = True

        if any(phrase in activity_text for phrase in ['add comments', 'include comments', 'write comments', 'comment your code']):
            requirements['comments'] = True

        if any(phrase in activity_text for phrase in ['return statement', 'return value', 'return from function']):
            requirements['return_statement'] = True

        if any(phrase in activity_text for phrase in ['main function', 'int main', 'write main function']):
            requirements['main_function'] = True

        if any(phrase in activity_text for phrase in ['include stdio.h', 'include header', 'standard library']):
            requirements['include_stdio'] = True

        if any(phrase in activity_text for phrase in ['arithmetic operators', 'mathematical operations', 'calculations']):
            requirements['arithmetic'] = True

        if any(phrase in activity_text for phrase in ['comparison operators', 'relational operators', 'compare values']):
            requirements['comparison'] = True

        if any(phrase in activity_text for phrase in ['logical operators', 'boolean operators', '&& || !']):
            requirements['logical_operators'] = True

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
            if not req_value:
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

        # Additionally, check for basic programming elements that are typically expected
        # If the code uses certain features, consider them as requirements
        basic_requirements = ['input_output', 'variables', 'main_function', 'include_stdio', 'return_statement']

        for req_name in basic_requirements:
            if req_name in requirements and requirements[req_name]:
                continue  # Already checked above

            # Check if code has this element
            met, count, feedback_str = checkers[req_name](code)
            if met:
                # If code has this element, consider it required and met
                total_required_points += points_map[req_name]
                met_points += points_map[req_name]
                met_requirements.append(feedback_str)

        # Calculate requirement score as percentage of met requirements
        if total_required_points > 0:
            requirement_score = (met_points / total_required_points) * 100
        else:
            requirement_score = 100  # No requirements detected, no penalty

        # Generate feedback
        feedback_parts = []
        if missing_requirements:
            feedback_parts.append(f"Missing required elements: {', '.join(missing_requirements)}.")
        if met_requirements:
            feedback_parts.append(f"Successfully implemented: {', '.join(met_requirements)}.")
        if not missing_requirements and not met_requirements:
            feedback_parts.append("No specific requirements detected in activity description.")

        # Remove trailing dots from each feedback part to avoid double dots when joining
        cleaned_feedback_parts = [part.rstrip('. ') for part in feedback_parts]
        return max(0, requirement_score), '. '.join(cleaned_feedback_parts)

    def normalize_code(self, code):
        """Normalize code by removing comments, normalizing whitespace, replacing literals, and user-defined identifiers with VAR to detect similarity despite variable renaming."""
        # Remove single-line comments
        code = re.sub(r'//.*', '', code)
        # Remove multi-line comments
        code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)

        # Remove preprocessor directives
        code = re.sub(r'#.*', '', code)

        # Normalize whitespace: replace multiple spaces/tabs with single space, strip lines
        lines = code.split('\n')
        normalized_lines = []
        for line in lines:
            line = re.sub(r'\s+', ' ', line.strip())
            if line:
                normalized_lines.append(line)
        code = '\n'.join(normalized_lines)

        # Replace string literals with STR_LITERAL
        code = re.sub(r'"[^"]*"', 'STR_LITERAL', code)

        # Replace character literals with CHAR_LITERAL
        code = re.sub(r"'[^']'", 'CHAR_LITERAL', code)

        # Replace numeric literals with NUM_LITERAL (including floats)
        code = re.sub(r'\b\d+\.?\d*\b', 'NUM_LITERAL', code)

        # C keywords and common library functions to preserve
        c_keywords = {
            'auto', 'break', 'case', 'char', 'const', 'continue', 'default', 'do', 'double', 'else', 'enum', 'extern',
            'float', 'for', 'goto', 'if', 'int', 'long', 'register', 'return', 'short', 'signed', 'sizeof', 'static',
            'struct', 'switch', 'typedef', 'union', 'unsigned', 'void', 'volatile', 'while'
        }
        library_functions = {
            'printf', 'scanf', 'main', 'malloc', 'free', 'strlen', 'strcpy', 'strcmp', 'fopen', 'fclose', 'fprintf',
            'fscanf', 'sprintf', 'sscanf', 'gets', 'puts', 'getchar', 'putchar', 'atoi', 'atof', 'rand', 'srand',
            'time', 'exit', 'abs', 'sqrt', 'pow', 'sin', 'cos', 'tan', 'log', 'exp', 'ceil', 'floor'
        }

        # Find all words in the code
        words = set(re.findall(r'\b\w+\b', code))

        # Replace user-defined identifiers with VAR
        normalized = code
        for word in words:
            if word not in c_keywords and word not in library_functions and word not in ['STR_LITERAL', 'CHAR_LITERAL', 'NUM_LITERAL']:
                normalized = re.sub(r'\b' + re.escape(word) + r'\b', 'VAR', normalized)

        return normalized

    def check_similarity(self, activity_id, code, student_id):
        """Check similarity with other submissions using sequence matching, accounting for variable renaming."""
        try:
            if not code or not isinstance(code, str) or len(code.strip()) == 0:
                return 100, "No valid code submitted for similarity check."

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

            other_codes = [row[0] for row in submissions if row[0] and isinstance(row[0], str)]

            if not other_codes:
                return 100, "No similar submissions found."

            # Normalize codes to handle variable renaming
            try:
                normalized_code = self.normalize_code(code)
            except Exception as e:
                logger.error(f"Failed to normalize submitted code: {str(e)}")
                return 100, "Failed to process submitted code for similarity check."

            normalized_other_codes = []
            for other_code in other_codes:
                try:
                    normalized_other_codes.append(self.normalize_code(other_code))
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

            if max_sim_percent > 80: similarity_level = "very high"
            elif max_sim_percent > 60: similarity_level = "high"
            elif max_sim_percent > 40: similarity_level = "moderate"
            elif max_sim_percent > 20: similarity_level = "low"
            else: similarity_level = "very low"

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
import subprocess
import tempfile
import os
import re
import datetime
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
                SELECT title, description, instructions, starter_code, due_date,
                        correctness_weight, syntax_weight, logic_weight, similarity_weight
                FROM activities WHERE id = %s
            """, (activity_id,))
            activity = cur.fetchone()
            cur.close()

            if not activity:
                return {'error': 'Activity not found'}

            title, description, instructions, starter_code, due_date, correctness_w, syntax_w, logic_w, similarity_w = activity

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

            # Correctness and Logic analysis
            correctness_score, logic_score, ast_feedback = self.check_ast_with_requirements(
                code, requirements, requirement_score
            )

            # Apply requirement penalty to correctness score
            correctness_score = correctness_score * (requirement_score / 100)

            # Similarity check - only if syntax is correct
            if syntax_score >= 50:
                similarity_score, sim_feedback = self.check_similarity(activity_id, code, student_id)
            else:
                similarity_score, sim_feedback = 100, "Skipped similarity check due to syntax errors"

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
            return {'error': f'Grading failed: {str(e)}'}

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
                return 100, "Syntax is correct"
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
        except Exception as e:
            return 0, f"Syntax check failed: {str(e)}"

    def check_ast_with_requirements(self, code, requirements, requirement_score):
        """Check correctness and logic using analysis."""
        correctness_score, logic_score, syntax_score, enhanced_feedback = self.enhanced_ml_grading(code)

        return correctness_score, logic_score, enhanced_feedback

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
            final_logic = rule_logic  # Use rule-based logic score for better accuracy
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

    def analyze_c_code_logic(self, code):
        """Analyze C code logic complexity and flow with improved criteria."""
        score = 40  # Base score increased for better baseline

        # Control Flow Complexity
        if_count = code.count('if ') + code.count('else if')
        loop_count = code.count('for ') + code.count('while ') + code.count('do ')
        switch_count = code.count('switch ')
        total_control = if_count + loop_count + switch_count

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
            # Reduce penalty for no control flow if code is short/simple
            lines = [line.strip() for line in code.split('\n') if line.strip()]
            if len(lines) <= 5:
                score += 10  # Small program, no penalty
            else:
                score -= 5  # Larger program missing control flow

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

        score += min(20, algorithm_indicators * 6)  # Slightly higher weight

        # Data Processing
        array_usage = code.count('[') + code.count(']')
        score += 15 if array_usage > 0 else 0  # Increased weight for arrays

        # Error Handling (basic check for NULL and conditional usage)
        error_patterns = code.count('NULL') + code.count('if (') + code.count('else')
        score += 15 if error_patterns > 0 else 0  # Increased weight

        # Code Efficiency (nested loops)
        nested_loops = max(0, code.count('for (') + code.count('while (') - 1)
        if nested_loops == 0:
            score += 20
        elif nested_loops <= 2:
            score += 15
        else:
            score += 10

        # Check for use of break/continue for loop control
        if 'break;' in code or 'continue;' in code:
            score += 10  # Increased weight

        # Additional logic checks for better variation
        # Check for proper loop initialization
        loop_init_patterns = code.count('for (int ') + code.count('for (i =') + code.count('while (')
        score += min(15, loop_init_patterns * 3)  # Increased weight

        # Check for function calls within logic
        func_in_logic = code.count('if (') + code.count('while (') + code.count('for (')
        if func_in_logic > 0:
            score += min(15, func_in_logic * 2)  # Increased weight

        # Penalize for missing logic in simple programs
        lines = code.split('\n')
        code_lines = [line.strip() for line in lines if line.strip()]
        if len(code_lines) > 5 and total_control == 0:
            score -= 10  # Reduced penalty

        return min(100, max(0, score))

    def analyze_c_code_detailed_feedback(self, code):
        """Provide detailed feedback on C code analysis."""
        feedback_parts = []

        # Analyze code length
        lines = [line for line in code.split('\n') if line.strip()]
        code_length = len(lines)
        
        if code_length < 10:
            feedback_parts.append("Code is quite short - consider adding more functionality")
        elif code_length > 70:
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
            'logical_operators': 5,  # Adjusted to give points for logical operators
            'loops': 10,
            'functions': 10,
            'arrays': 10,
            'pointers': 10,
            'switch': 10,
            'comments': 5,
            'arithmetic': 5,
            'comparison': 5,
            'specific_content': 5  # Adjusted to give points for specific content
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

    def check_similarity(self, activity_id, code, student_id):
        """Check similarity with other submissions using token-based similarity."""
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

            other_codes = [row[0] for row in submissions]

            if not other_codes:
                return 100, "No similar submissions found."

            # Tokenize codes by splitting on non-alphanumeric characters
            def tokenize(text):
                return set(re.findall(r'\b\w+\b', text))
            code_tokens = tokenize(code)
            max_similarity = 0

            for other_code in other_codes:
                other_tokens = tokenize(other_code)
                intersection = code_tokens.intersection(other_tokens)
                union = code_tokens.union(other_tokens)
                similarity = len(intersection) / len(union) if union else 0
                if similarity > max_similarity:
                    max_similarity = similarity

            
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
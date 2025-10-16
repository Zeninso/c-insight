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

            # Check for major requirement failures - if activity not implemented properly, set all scores to zero
            if requirement_score < 30:
                correctness_score = 0
                syntax_score = 0
                logic_score = 0
                similarity_score = 0
                ast_feedback = f"Activity requirements not met (score: {requirement_score:.1f}%); submission appears incomplete or incorrect - all scores set to zero."
                sim_feedback = "Similarity check skipped due to major requirement failures."
            # If syntax score is below threshold, assign zero to all scores and skip further checks
            elif syntax_score < 85:
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

                # Apply requirement penalty to correctness score for moderate requirement issues
                if requirement_score < 70:
                    penalty_factor = (requirement_score / 100) ** 2
                    correctness_score = correctness_score * penalty_factor
                    reduction_percent = 100 - (penalty_factor * 100)
                    ast_feedback += f" Correctness score reduced by {reduction_percent:.1f}% due to unmet requirements."

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
                f"Requirements Check: {requirement_score:.1f}% - {requirement_feedback}",
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

    def analyze_c_code_logic(self, code, requirements=None):
        """Analyze C code logic complexity and flow with enhanced criteria."""
        score = 50  # Increased base score for better baseline

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
            # More generous scoring for control flow complexity - higher scores for proper logic
            if total_control <= 3:
                score += 30  # Increased from 25
            elif total_control <= 7:
                score += 25  # Increased from 20
            elif total_control <= 12:
                score += 20  # Increased from 15
            else:
                score += 15  # Increased from 10
        else:
            # Only penalize for missing control flow if it's explicitly required
            if control_flow_required:
                lines = [line.strip() for line in code.split('\n') if line.strip()]
                if len(lines) > 5:
                    score -= 5  # Reduced penalty
            else:
                # Bonus if control flow not required but code is simple and clear
                score += 15  # Increased from 10

        # Algorithm Indicators with improved detection - higher weights for proper algorithms
        algorithm_indicators = 0
        code_lower = code.lower()

        # Basic algorithm patterns
        if 'sort' in code_lower or 'search' in code_lower:
            algorithm_indicators += 2  # Increased weight
        if '%' in code:  # Modulo operations often used in algorithms
            algorithm_indicators += 2
        if 'sqrt' in code or 'pow' in code:  # Mathematical functions
            algorithm_indicators += 2
        if '&&' in code or '||' in code:  # Logical operations
            algorithm_indicators += 1

        # Specific algorithm implementations - higher bonuses for proper implementations
        sorting_algorithms = ['bubble', 'insertion', 'selection', 'merge', 'quick', 'heap']
        search_algorithms = ['binary', 'linear', 'sequential']
        if any(alg in code_lower for alg in sorting_algorithms):
            algorithm_indicators += 5  # Increased from 3
        if any(alg in code_lower for alg in search_algorithms):
            algorithm_indicators += 5  # Increased from 3
        if 'recursion' in code_lower or 'recursive' in code_lower:
            algorithm_indicators += 5  # Increased from 3

        # Check for proper algorithm implementation patterns
        algorithm_quality_score = self.check_algorithm_quality(code)
        score += min(35, algorithm_indicators * 3 + algorithm_quality_score)  # Increased cap and multiplier

        # Data Processing - higher scores for proper array usage
        array_usage = code.count('[') + code.count(']')
        if requirements and requirements.get('arrays', False):
            score += 20 if array_usage > 0 else -5  # Increased bonus
        elif array_usage > 0:
            score += 20  # Increased bonus

        # Error Handling (enhanced check for NULL, bounds checking, and conditional usage) - higher rewards
        error_patterns = code.count('NULL') + code.count('if (') + code.count('else')
        bounds_checks = code.count('if (') + code.count('while (') + code.count('< ') + code.count('> ') + code.count('<=') + code.count('>=')
        error_handling_score = min(30, error_patterns * 3 + bounds_checks * 2)  # Increased multipliers and cap
        score += error_handling_score

        # Code Efficiency (nested loops and complexity analysis) - higher rewards for good efficiency
        if loop_count > 0:
            nested_loops = max(0, code.count('for (') + code.count('while (') - 1)
            efficiency_score = 0
            if nested_loops == 0:
                efficiency_score = 30  # Increased from 25
            elif nested_loops <= 2:
                efficiency_score = 25  # Increased from 20
            elif nested_loops <= 4:
                efficiency_score = 20  # Increased from 15
            else:
                efficiency_score = 10  # Increased from 5

            # Check for potential infinite loops
            infinite_loop_penalty = self.check_infinite_loops(code)
            efficiency_score -= infinite_loop_penalty

            score += efficiency_score

        # Check for use of break/continue for loop control - higher bonus for proper control
        if loop_count > 0 and ('break;' in code or 'continue;' in code):
            score += 15  # Increased from 12

        # Additional logic checks for better variation
        # Check for proper loop initialization and bounds - higher scores for good loops
        if loop_count > 0:
            loop_quality_score = self.check_loop_quality(code)
            score += loop_quality_score * 1.5  # Multiplier for better loop quality

        # Check for function calls within logic - higher bonus when functions are properly used
        if requirements and requirements.get('functions', False):
            func_in_logic = code.count('if (') + code.count('while (') + code.count('for (')
            if func_in_logic > 0:
                score += min(20, func_in_logic * 3)  # Increased weight
        else:
            # If functions not required, bonus for clean simple code
            score += 5

        # Reduced penalty for missing logic in simple programs
        lines = code.split('\n')
        code_lines = [line.strip() for line in lines if line.strip()]
        if len(code_lines) > 5 and total_control == 0 and control_flow_required:
            score -= 5  # Reduced from 10

        # Enhanced logic checks - higher weights for good practices
        # Check for proper variable initialization and usage
        var_logic_score = self.check_variable_logic(code)
        score += var_logic_score * 1.2  # Multiplier for variable logic

        # Check for logical consistency and potential errors
        logic_consistency_score = self.check_enhanced_logical_consistency(code)
        score += logic_consistency_score * 1.3  # Higher multiplier for consistency

        # Check for proper nesting and structure
        nesting_score = self.check_nesting_structure(code)
        score += nesting_score * 1.5  # Higher multiplier for good structure

        # Check for unreachable code patterns - less penalty for good code
        unreachable_score = self.check_unreachable_code(code)
        score += unreachable_score * 1.2  # Reduced penalty impact

        # Check for proper operator usage
        operator_score = self.check_operator_usage(code)
        score += operator_score * 1.4  # Higher multiplier for operator usage

        # Check for memory safety - higher bonus for safe code
        memory_score = self.check_memory_safety(code)
        score += memory_score * 1.5  # Higher multiplier for memory safety

        return min(100, max(0, score))


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
        well_met_requirements = []

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

        # FIXED: Only check requirements that are explicitly marked as required
        for req_name, checker in checkers.items():
            # Skip specific_content if there are no keywords to check
            if req_name == 'specific_content' and not requirements.get('specific_content'):
                continue
                
            # Check if this requirement is actually required in the activity
            is_required = False
            
            if req_name in requirements:
                req_data = requirements[req_name]
                if isinstance(req_data, dict):
                    # For requirements with semantic data
                    is_required = req_data.get('required', False)
                else:
                    # For simple boolean requirements
                    is_required = bool(req_data)
            
            # Only check and score requirements that are explicitly required
            if is_required:
                total_required_points += points_map[req_name]

                if req_name == 'specific_content':
                    met, count, feedback_str = checker(code)
                else:
                    met, count, feedback_str = checker(code)

                if met:
                    # Check if requirement is exceptionally well met
                    if req_name in ['if_else', 'loops', 'functions', 'arrays'] and count > 2:
                        well_met_requirements.append(f"{feedback_str} - excellent implementation!")
                    elif req_name == 'comments' and count > 3:
                        well_met_requirements.append(f"{feedback_str} - great documentation!")
                    elif req_name == 'specific_content' and count >= len(requirements['specific_content']) * 0.7:
                        well_met_requirements.append(f"{feedback_str} - good coverage of required content!")
                    else:
                        met_requirements.append(f"{feedback_str} - requirement met")
                    met_points += points_map[req_name]
                else:
                    missing_requirements.append(req_name.replace('_', ' '))

        # Calculate requirement score as percentage of met requirements
        if total_required_points > 0:
            requirement_score = (met_points / total_required_points) * 100
        else:
            requirement_score = 100  # No requirements detected, no penalty

        # Enhanced feedback generation with positive reinforcement
        feedback_parts = []
        
        # Show exceptionally well-met requirements first
        if well_met_requirements:
            feedback_parts.append(f"🌟 Excellent work: {', '.join(well_met_requirements)}")
        
        # Show regularly met requirements
        if met_requirements:
            feedback_parts.append(f"✅ Requirements met: {', '.join(met_requirements)}")
        
        # Only show missing requirements if there are any
        if missing_requirements:
            feedback_parts.append(f"❌ Missing required elements: {', '.join(missing_requirements)}")
        
        # If nothing was found at all
        if not missing_requirements and not met_requirements and not well_met_requirements:
            feedback_parts.append("No specific requirements detected in activity description")

        # Add overall requirement achievement feedback
        if requirement_score >= 90:
            achievement_feedback = "Outstanding! All requirements perfectly met."
        elif requirement_score >= 80:
            achievement_feedback = "Great job! Most requirements successfully implemented."
        elif requirement_score >= 70:
            achievement_feedback = "Good work! Requirements generally met with minor gaps."
        elif requirement_score >= 50:
            achievement_feedback = "Fair attempt. Some requirements met but significant gaps remain."
        else:
            achievement_feedback = "Needs improvement. Many requirements not yet implemented."
        
        if feedback_parts:
            final_feedback = f"{achievement_feedback} {' '.join(feedback_parts)}"
        else:
            final_feedback = achievement_feedback

        return max(0, requirement_score), final_feedback

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
                cur = mysql.connection.cursor()
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
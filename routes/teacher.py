from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from app import mysql
from datetime import datetime
from flask import Flask
from flask_mysqldb import MySQL
from flask_dance.contrib.google import make_google_blueprint
import os
from flask_dance.contrib.google import google
from flask import current_app as app
import MySQLdb
from io import BytesIO
from flask import send_file
import pandas as pd




teacher_bp = Blueprint('teacher', __name__)



@teacher_bp.route('/teacherDashboard')
def teacherDashboard():
    if 'username' not in session:
        flash('Please login first', 'error')
        return redirect(url_for('auth.login'))
    if session.get('role') != 'teacher':
        flash('Unauthorized access', 'error')
        return redirect(url_for('home.home'))
    
    # Notify teacher about finished activities
    notify_finished_activities()

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Get teacher ID
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    teacher_row = cur.fetchone()
    if not teacher_row:
        flash("Teacher not found", "error")
        return redirect(url_for('auth.login'))
    teacher_id = teacher_row['id']

    # Get unread notifications count
    unread_notifications_count = get_unread_notifications_count(teacher_id)

    # Get total classes
    cur.execute("SELECT COUNT(*) FROM classes WHERE teacher_id=%s", (teacher_id,))
    total_classes_result = cur.fetchone()
    total_classes = total_classes_result['COUNT(*)'] if total_classes_result else 0

    # Get first class id for view students link
    first_class_id = None
    if total_classes > 0:
        cur.execute("SELECT id FROM classes WHERE teacher_id=%s ORDER BY created_at ASC LIMIT 1", (teacher_id,))
        first_class = cur.fetchone()
        first_class_id = first_class['id'] if first_class else None

    # Get total students (across all classes)
    cur.execute("""
        SELECT COUNT(DISTINCT e.student_id)
        FROM enrollments e
        JOIN classes c ON e.class_id = c.id
        WHERE c.teacher_id = %s
    """, (teacher_id,))
    total_students_result = cur.fetchone()
    total_students = total_students_result['COUNT(DISTINCT e.student_id)'] if total_students_result else 0

    # Get recent activities (last 5) with submission progress
    cur.execute("""
        SELECT a.title, a.created_at, c.name as class_name,
               (SELECT COUNT(*) FROM enrollments WHERE class_id = a.class_id) as total_students,
               (SELECT COUNT(DISTINCT s.student_id) FROM submissions s WHERE s.activity_id = a.id) as submitted_count
        FROM activities a
        JOIN classes c ON a.class_id = c.id
        WHERE a.teacher_id = %s
        ORDER BY a.created_at DESC
        LIMIT 5
    """, (teacher_id,))
    recent_activities = cur.fetchall()

    # Get pending submissions (submissions that have not been graded yet)
    cur.execute("""
        SELECT COUNT(*)
        FROM submissions s
        JOIN activities a ON s.activity_id = a.id
        WHERE a.teacher_id = %s AND s.correctness_score IS NULL
    """, (teacher_id,))
    pending_submissions_result = cur.fetchone()
    pending_submissions = pending_submissions_result['COUNT(*)'] if pending_submissions_result else 0

    cur.close()

    return render_template('teacher_dashboard.html',
                          first_name=session['first_name'],
                          total_classes=total_classes,
                          total_students=total_students,
                          recent_activities=recent_activities,
                          pending_submissions=pending_submissions,
                          unread_notifications_count=unread_notifications_count,
                          first_class_id=first_class_id)
        

@teacher_bp.route('/analytics')
def teacherAnalytics():
    if 'username' not in session or session.get('role') != 'teacher':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Get teacher ID
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    teacher_row = cur.fetchone()
    if not teacher_row:
        flash("Teacher not found", "error")
        return redirect(url_for('auth.login'))
    teacher_id = teacher_row['id']

    # Get class filter
    class_id = request.args.get('class_id')
    if class_id:
        try:
            class_id = int(class_id)
        except ValueError:
            class_id = None

    # Get all classes for the teacher
    cur.execute("SELECT id, name FROM classes WHERE teacher_id = %s ORDER BY name", (teacher_id,))
    classes = cur.fetchall()

    # Get students in teacher's classes (filtered by class if specified)
    if class_id:
        # Get students only from the specified class
        cur.execute("""
            SELECT DISTINCT u.id, u.first_name, u.last_name, u.username
            FROM users u
            JOIN enrollments e ON u.id = e.student_id
            JOIN classes c ON e.class_id = c.id
            WHERE c.teacher_id = %s AND c.id = %s
            ORDER BY u.first_name, u.last_name
        """, (teacher_id, class_id))
    else:
        # Get students from all teacher's classes
        cur.execute("""
            SELECT DISTINCT u.id, u.first_name, u.last_name, u.username
            FROM users u
            JOIN enrollments e ON u.id = e.student_id
            JOIN classes c ON e.class_id = c.id
            WHERE c.teacher_id = %s
            ORDER BY u.first_name, u.last_name
        """, (teacher_id,))
    students = cur.fetchall()

    # For each student, get submission scores over time
    student_progress = []
    for student in students:
        cur.execute("""
            SELECT s.submitted_at,
                   ((s.correctness_score * a.correctness_weight / 100) +
                    (s.syntax_score * a.syntax_weight / 100) +
                    (s.logic_score * a.logic_weight / 100) +
                    (s.similarity_score * a.similarity_weight / 100)) as total_score,
                    s.correctness_score, s.syntax_score, s.logic_score, s.similarity_score
            FROM submissions s
            JOIN activities a ON s.activity_id = a.id
            JOIN classes c ON a.class_id = c.id
            WHERE s.student_id = %s AND c.teacher_id = %s
            ORDER BY s.submitted_at ASC
        """, (student['id'], teacher_id))
        submissions = cur.fetchall()

        # Aggregate scores by date
        progress_data = []
        total_score_sum = 0
        correctness_sum = 0
        syntax_sum = 0
        logic_sum = 0
        similarity_sum = 0

        for sub in submissions:
            progress_data.append({
                'date': sub['submitted_at'].strftime('%Y-%m-%d') if sub['submitted_at'] else None,
                'total_score': float(sub['total_score']),
                'correctness_score': float(sub['correctness_score']),
                'syntax_score': float(sub['syntax_score']),
                'logic_score': float(sub['logic_score']),
                'similarity_score': float(sub['similarity_score'])
            })
            total_score_sum += sub['total_score']
            correctness_sum += sub['correctness_score']
            syntax_sum += sub['syntax_score']
            logic_sum += sub['logic_score']
            similarity_sum += sub['similarity_score']

        # Calculate averages
        num_submissions = len(submissions)
        avg_total = total_score_sum / num_submissions if num_submissions > 0 else 0
        avg_correctness = correctness_sum / num_submissions if num_submissions > 0 else 0
        avg_syntax = syntax_sum / num_submissions if num_submissions > 0 else 0
        avg_logic = logic_sum / num_submissions if num_submissions > 0 else 0
        avg_similarity = similarity_sum / num_submissions if num_submissions > 0 else 0

        # Get classes for this student
        cur.execute("""
            SELECT c.id, c.name
            FROM classes c
            JOIN enrollments e ON c.id = e.class_id
            WHERE e.student_id = %s AND c.teacher_id = %s
            ORDER BY c.name
        """, (student['id'], teacher_id))
        student_classes = cur.fetchall()

        student_progress.append({
            'student': student,
            'progress': progress_data,
            'stats': {
                'total_submissions': num_submissions,
                'avg_total_score': round(avg_total, 1),
                'avg_correctness': round(avg_correctness, 1),
                'avg_syntax': round(avg_syntax, 1),
                'avg_logic': round(avg_logic, 1),
                'avg_similarity': round(avg_similarity, 1)
            },
            'classes': student_classes
        })

    # Get unread notifications count
    unread_notifications_count = get_unread_notifications_count(teacher_id)

    cur.close()

    import json
    # Ensure student_progress_json is always a valid JSON string
    try:
        student_progress_json = json.dumps(student_progress) if student_progress else '[]'
    except (TypeError, ValueError):
        student_progress_json = '[]'

    return render_template('teacher_analytics.html', student_progress=student_progress, student_progress_json=student_progress_json, first_name=session['first_name'], unread_notifications_count=unread_notifications_count, classes=classes, class_id=class_id)

@teacher_bp.route('/grades')
def teacherGrades():
    if 'username' not in session or session.get('role') != 'teacher':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Get teacher ID
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    teacher_id = cur.fetchone()['id']

    # Get class filter
    class_id = request.args.get('class_id')
    if class_id:
        try:
            class_id = int(class_id)
        except ValueError:
            class_id = None

    # Get activity filter
    activity_id = request.args.get('activity_id')
    if activity_id:
        try:
            activity_id = int(activity_id)
        except ValueError:
            activity_id = None
            
    # Get similarity filter
    show_similar = request.args.get('show_similar') == 'true'

    # Get all classes for dropdown
    cur.execute("SELECT id, name FROM classes WHERE teacher_id = %s ORDER BY name", (teacher_id,))
    classes = cur.fetchall()

    # Get activities for filter dropdown (filtered by class if selected)
    if class_id:
        cur.execute("SELECT id, title FROM activities WHERE teacher_id = %s AND class_id = %s ORDER BY title", (teacher_id, class_id))
    else:
        cur.execute("SELECT id, title FROM activities WHERE teacher_id = %s ORDER BY title", (teacher_id,))
    activities = cur.fetchall()

    # Query submissions with grades and code for teacher's activities
    base_query = """
        SELECT s.id as submission_id, s.student_id, u.first_name, u.last_name, u.username,
               a.title as activity_title, a.class_id, c.name as class_name,
               s.code, s.submitted_at,
               s.correctness_score, s.syntax_score, s.logic_score, s.similarity_score,
               a.correctness_weight, a.syntax_weight, a.logic_weight, a.similarity_weight,
               ((s.correctness_score * a.correctness_weight / 100) +
                (s.syntax_score * a.syntax_weight / 100) +
                (s.logic_score * a.logic_weight / 100) +
                (s.similarity_score * a.similarity_weight / 100)) as total_score,
               s.feedback
        FROM submissions s
        JOIN users u ON s.student_id = u.id
        JOIN activities a ON s.activity_id = a.id
        JOIN classes c ON a.class_id = c.id
        WHERE a.teacher_id = %s
    """
    params = [teacher_id]

    if class_id:
        base_query += " AND a.class_id = %s"
        params.append(class_id)

    if activity_id:
        base_query += " AND a.id = %s"
        params.append(activity_id)

    base_query += " ORDER BY s.submitted_at DESC"
    cur.execute(base_query, params)

    submissions = cur.fetchall()
    
    # Handle similarity filtering
    display_submissions = submissions
    grouped_submissions = []

    if show_similar:
        if activity_id and submissions:
            # Group submissions with high structural similarity for side-by-side comparison
            grouped_submissions = group_similar_submissions(submissions, similarity_threshold=80)

            # Prepare display submissions with group metadata
            display_submissions = []
            for group in grouped_submissions:
                if len(group) > 1:
                    # Mark submissions as part of a similar group
                    for submission in group:
                        submission['is_similar_group'] = True
                        submission['group_members'] = len(group)
                        submission['group_submissions'] = group
                display_submissions.extend(group)
        else:
            # Show submissions with low similarity scores (high actual similarity - potential copying)
            display_submissions = [
                s for s in submissions
                if s.get('similarity_score') is not None and s['similarity_score'] <= 60
            ]

    # Get unread notifications count
    unread_notifications_count = get_unread_notifications_count(teacher_id)

    cur.close()

    return render_template('teacher_grades.html',
                         submissions=display_submissions,
                         activities=activities,
                         classes=classes,
                         first_name=session['first_name'],
                         unread_notifications_count=unread_notifications_count,
                         show_similar=show_similar,
                         activity_id=activity_id,
                         class_id=class_id,
                         grouped_submissions=grouped_submissions if show_similar else None)

def group_similar_submissions(submissions, similarity_threshold=70):
    """Group submissions that have high similarity to each other"""
    if not submissions:
        return []
    
    groups = []
    processed_ids = set()
    
    for i, submission1 in enumerate(submissions):
        if submission1['submission_id'] in processed_ids:
            continue
            
        current_group = [submission1]
        processed_ids.add(submission1['submission_id'])
        
        for j, submission2 in enumerate(submissions):
            if (submission2['submission_id'] not in processed_ids and 
                i != j and 
                calculate_code_similarity(submission1['code'], submission2['code']) >= similarity_threshold):
                
                current_group.append(submission2)
                processed_ids.add(submission2['submission_id'])
        
        if len(current_group) > 1:  # Only add groups with multiple submissions
            groups.append(current_group)
    
    # Add single submissions that weren't grouped
    for submission in submissions:
        if submission['submission_id'] not in processed_ids:
            groups.append([submission])
    
    return groups


def calculate_code_similarity(code1, code2):
    """Calculate similarity between two code snippets, accounting for variable renaming"""
    if not code1 or not code2:
        return 0

    # Normalize code by replacing user-defined identifiers with VAR
    def normalize_code(code):
        import re
        # C keywords and common library functions to preserve
        c_keywords = {
            'auto', 'break', 'case', 'char', 'const', 'continue', 'default', 'do', 'double', 'else', 'enum', 'extern',
            'float', 'for', 'goto', 'if', 'int', 'long', 'register', 'return', 'short', 'signed', 'sizeof', 'static',
            'struct', 'switch', 'typedef', 'union', 'unsigned', 'void', 'volatile', 'while'
        }
        library_functions = {
            'printf', 'scanf', 'main', 'malloc', 'free', 'strlen', 'strcpy', 'strcmp', 'fopen', 'fclose', 'fprintf',
            'fscanf', 'sprintf', 'sscanf', 'gets', 'puts', 'getchar', 'putchar', 'atoi', 'atof', 'rand', 'srand',
            'time', 'exit', 'abs', 'sqrt', 'pow', 'sin', 'cos', 'tan'
        }

        # Remove comments first
        code = re.sub(r'//.*', '', code)
        code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)

        # Find all words in the code
        words = set(re.findall(r'\b\w+\b', code))

        # Replace user-defined identifiers with VAR
        normalized = code
        for word in words:
            if word not in c_keywords and word not in library_functions:
                normalized = re.sub(r'\b' + re.escape(word) + r'\b', 'VAR', normalized)

        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized.strip()

    norm1 = normalize_code(code1)
    norm2 = normalize_code(code2)

    if not norm1 or not norm2:
        return 0

    # Use sequence matching for similarity calculation
    from difflib import SequenceMatcher
    return int(SequenceMatcher(None, norm1, norm2).ratio() * 100)



@teacher_bp.route('/generate_grade_report', methods=['POST'])
def generate_grade_report():
    if 'username' not in session or session.get('role') != 'teacher':
        return jsonify({'error': 'Unauthorized access'}), 401

    try:
        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

        # Get teacher ID
        cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
        teacher_id = cur.fetchone()['id']

        # Get filter parameters from the form
        class_id_str = request.form.get('class_id')
        activity_id_str = request.form.get('activity_id')

        class_id = None
        if class_id_str and class_id_str.strip():
            try:
                class_id = int(class_id_str)
            except ValueError:
                pass

        activity_id = None
        if activity_id_str and activity_id_str.strip():
            try:
                activity_id = int(activity_id_str)
            except ValueError:
                pass

        # First, get relevant students and activities based on filters
        if class_id:
            # Filter by class: get students in class and activities in class
            cur.execute("""
                SELECT DISTINCT u.id as student_id, u.first_name, u.last_name, c.name as class_name
                FROM users u
                JOIN enrollments e ON u.id = e.student_id
                JOIN classes c ON e.class_id = c.id
                WHERE c.id = %s AND c.teacher_id = %s
                ORDER BY u.last_name, u.first_name
            """, (class_id, teacher_id))
            students = cur.fetchall()

            cur.execute("""
                SELECT id, title
                FROM activities
                WHERE class_id = %s AND teacher_id = %s
                ORDER BY title
            """, (class_id, teacher_id))
            activities = cur.fetchall()
        elif activity_id:
            # Filter by activity: get students who submitted the activity, and only that activity
            cur.execute("""
                SELECT DISTINCT u.id as student_id, u.first_name, u.last_name, c.name as class_name
                FROM submissions s
                JOIN users u ON s.student_id = u.id
                JOIN activities a ON s.activity_id = a.id
                JOIN classes c ON a.class_id = c.id
                WHERE a.id = %s AND a.teacher_id = %s
                ORDER BY u.last_name, u.first_name
            """, (activity_id, teacher_id))
            students = cur.fetchall()

            cur.execute("""
                SELECT id, title
                FROM activities
                WHERE id = %s AND teacher_id = %s
            """, (activity_id, teacher_id))
            activities = cur.fetchall()
        else:
            # No filters: get all students and activities for teacher
            cur.execute("""
                SELECT DISTINCT u.id as student_id, u.first_name, u.last_name, c.name as class_name
                FROM users u
                JOIN enrollments e ON u.id = e.student_id
                JOIN classes c ON e.class_id = c.id
                WHERE c.teacher_id = %s
                ORDER BY u.last_name, u.first_name
            """, (teacher_id,))
            students = cur.fetchall()

            cur.execute("""
                SELECT id, title
                FROM activities
                WHERE teacher_id = %s
                ORDER BY title
            """, (teacher_id,))
            activities = cur.fetchall()

        cur.close()

        if not students:
            return jsonify({'error': 'No students found to generate report'}), 404

        if not activities:
            return jsonify({'error': 'No activities found to generate report'}), 404

        # Create student DataFrame
        student_df = pd.DataFrame(students)
        student_df['Name'] = student_df['first_name'] + ' ' + student_df['last_name']
        student_df = student_df[['student_id', 'Name', 'class_name']]
        student_df = student_df.rename(columns={'class_name': 'Class'})

        # For each student, get submissions for relevant activities
        submission_data = []
        for _, student in student_df.iterrows():
            student_row = {'student_id': student['student_id'], 'Name': student['Name'], 'Class': student['Class']}
            for act in activities:
                act_id = act['id']
                act_title = act['title']

                # Get submission for this student and activity
                cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
                if class_id or activity_id:
                    # Use the filter to get submissions
                    query = """
                        SELECT s.submitted_at,
                               ROUND(((s.correctness_score * a.correctness_weight / 100) +
                                      (s.syntax_score * a.syntax_weight / 100) +
                                      (s.logic_score * a.logic_weight / 100) +
                                      (s.similarity_score * a.similarity_weight / 100)), 2) as total_score
                        FROM submissions s
                        JOIN activities a ON s.activity_id = a.id
                    """
                    params = []
                    if class_id:
                        query += " JOIN classes c ON a.class_id = c.id WHERE s.student_id = %s AND c.id = %s AND a.id = %s"
                        params = [student['student_id'], class_id, act_id]
                    elif activity_id:
                        query += " JOIN classes c ON a.class_id = c.id WHERE s.student_id = %s AND a.id = %s"
                        params = [student['student_id'], act_id]
                    else:
                        query += " WHERE s.student_id = %s AND a.id = %s"
                        params = [student['student_id'], act_id]

                    cur.execute(query, params)
                else:
                    # No filter, but ensure activity belongs to teacher's classes
                    cur.execute("""
                        SELECT s.submitted_at,
                               ROUND(((s.correctness_score * a.correctness_weight / 100) +
                                      (s.syntax_score * a.syntax_weight / 100) +
                                      (s.logic_score * a.logic_weight / 100) +
                                      (s.similarity_score * a.similarity_weight / 100)), 2) as total_score
                        FROM submissions s
                        JOIN activities a ON s.activity_id = a.id
                        JOIN classes c ON a.class_id = c.id
                        WHERE s.student_id = %s AND a.id = %s AND c.teacher_id = %s
                    """, (student['student_id'], act_id, teacher_id))

                submission = cur.fetchone()
                cur.close()

                if submission:
                    submitted_at = submission['submitted_at'].strftime('%m/%d/%Y %H:%M') if submission['submitted_at'] else 'N/A'
                    score = submission['total_score'] if submission['total_score'] is not None else 'N/A'
                else:
                    submitted_at = 'Not Submitted'
                    score = 'N/A'

                # Add to row
                col_date = f"{act_title} Submitted At"
                col_score = f"{act_title} Score"
                student_row[col_date] = submitted_at
                student_row[col_score] = score

            submission_data.append(student_row)

        # Create the pivoted DataFrame
        report_df = pd.DataFrame(submission_data)

        # Reorder columns: Name first, then activity columns (sorted by activity title), then Class last
        activity_cols = []
        for act in sorted(activities, key=lambda x: x['title']):
            activity_cols.extend([f"{act['title']} Submitted At", f"{act['title']} Score"])

        cols_order = ['Name'] + activity_cols + ['Class']
        report_df = report_df[cols_order]

        # Create summary: average scores per activity
        summary_data = {}
        for act in activities:
            act_title = act['title']
            scores = []
            for row in submission_data:
                score_col = f"{act_title} Score"
                if row[score_col] != 'N/A':
                    try:
                        scores.append(float(row[score_col]))
                    except ValueError:
                        pass
            if scores:
                avg_score = sum(scores) / len(scores)
                summary_data[act_title] = round(avg_score, 2)
            else:
                summary_data[act_title] = 'N/A'

        summary_df = pd.DataFrame([summary_data])
        summary_df.insert(0, 'Metric', 'Average Score')

        # Create Excel file in memory
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            workbook = writer.book
            header_format = workbook.add_format({
                'bold': True,
                'font_size': 12,
                'align': 'center',
                'valign': 'vcenter',
                'bg_color': "#BE95C6",
                'font_color': 'white',
                'border': 1,
                'text_wrap': True
            })

            title_format = workbook.add_format({
                'bold': True,
                'font_size': 16,
                'align': 'center',
                'valign': 'vcenter',
                'text_wrap': True
            })

            data_format = workbook.add_format({
                'text_wrap': True,
                'align': 'left',
                'valign': 'top'
            })

            # Create worksheets
            worksheet1 = workbook.add_worksheet('Student Grades')
            worksheet2 = workbook.add_worksheet('Summary')

            # Student Grades sheet formatting
            num_cols = len(report_df.columns)
            title_text = f'Grade Report - Generated on {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
            teacher_text = f'Teacher: {session["first_name"]} {session["last_name"]}'
            worksheet1.merge_range(0, 0, 0, num_cols - 1, title_text, title_format)
            worksheet1.merge_range(1, 0, 1, num_cols - 1, teacher_text, title_format)

            # Add headers with formatting
            for col_num, value in enumerate(report_df.columns.values):
                worksheet1.write(2, col_num, value, header_format)

            # Write data rows with text wrapping
            for row_idx in range(len(report_df)):
                row_num = 3 + row_idx
                row_data = report_df.iloc[row_idx]
                for col_num in range(num_cols):
                    worksheet1.write(row_num, col_num, row_data.iloc[col_num], data_format)

            # Auto-adjust columns' width
            for idx, col in enumerate(report_df.columns):
                max_len = max(
                    report_df[col].astype(str).map(len).max(),
                    len(str(col))
                ) + 2
                worksheet1.set_column(idx, idx, min(max_len, 20))

            # Summary sheet formatting
            num_sum_cols = len(summary_df.columns)
            title_text = f'Summary Report - Generated on {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
            teacher_text = f'Teacher: {session["first_name"]} {session["last_name"]}'
            worksheet2.merge_range(0, 0, 0, num_sum_cols - 1, title_text, title_format)
            worksheet2.merge_range(1, 0, 1, num_sum_cols - 1, teacher_text, title_format)

            # Add headers with formatting for summary
            for col_num, value in enumerate(summary_df.columns.values):
                worksheet2.write(2, col_num, value, header_format)

            # Write summary data row with text wrapping
            summary_row_data = summary_df.iloc[0]
            for col_num in range(num_sum_cols):
                worksheet2.write(3, col_num, summary_row_data.iloc[col_num], data_format)

            # Auto-adjust columns' width for summary sheet
            for idx, col in enumerate(summary_df.columns):
                max_len = max(
                    summary_df[col].astype(str).map(len).max(),
                    len(str(col))
                ) + 2
                worksheet2.set_column(idx, idx, min(max_len, 20))

        output.seek(0)

        # Create response with Excel file
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'grade_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        )

    except Exception as e:
        if 'cur' in locals():
            cur.close()
        return jsonify({'error': str(e)}), 500

@teacher_bp.route('/activities', methods=['GET', 'POST'])
def teacherActivities():
    if 'username' not in session or session.get('role') != 'teacher':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Get teacher ID
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    teacher_row = cur.fetchone()
    if not teacher_row:
        flash("Teacher not found", "error")
        return redirect(url_for('auth.login'))
    teacher_id = teacher_row['id']

    # Get unread notifications count
    unread_notifications_count = get_unread_notifications_count(teacher_id)

    # Get classes for the teacher
    cur.execute("""
        SELECT id, name, description
        FROM classes
        WHERE teacher_id = %s
        ORDER BY name
    """, (teacher_id,))
    classes = cur.fetchall()

    cur.execute("""
        SELECT  a.id, a.teacher_id, a.class_id, a.title, a.description, a.instructions,
                a.starter_code, a.due_date, a.correctness_weight, a.syntax_weight,
                a.logic_weight, a.similarity_weight, a.created_at,
                COUNT(s.id) AS submission_count, c.name AS class_name
        FROM activities a
        LEFT JOIN submissions s ON a.id = s.activity_id
        LEFT JOIN classes c ON a.class_id = c.id
        WHERE a.teacher_id = %s
        GROUP BY a.id
        ORDER BY a.created_at DESC
    """, (teacher_id,))
    activities = cur.fetchall()
    cur.close()

    #  Convert to dicts and format datetime fields
    activities_list = []
    for activity in activities:
        class_name = activity['class_name']
        if activity['class_id'] is None:
            class_name = 'No Class'
        elif class_name is None:
            class_name = 'Class Deleted'
        elif class_name == '':
            class_name = 'Unnamed Class'
        # else keep class_name

        activities_list.append({
            'id': activity['id'],
            'teacher_id': activity['teacher_id'],
            'class_id': activity['class_id'],
            'title': activity['title'],
            'description': activity['description'],
            'instructions': activity['instructions'],
            'starter_code': activity['starter_code'],
            'due_date': activity['due_date'],
            'correctness_weight': activity['correctness_weight'],
            'syntax_weight': activity['syntax_weight'],
            'logic_weight': activity['logic_weight'],
            'similarity_weight': activity['similarity_weight'],
            'created_at': activity['created_at'],
            'submission_count': activity['submission_count'],
            'class_name': class_name
        })

    # Convert classes to dicts
    classes_list = []
    for class_item in classes:
        classes_list.append({
            'id': class_item['id'],
            'name': class_item['name'],
            'description': class_item['description']
        })

    return render_template('teacher_activities.html', activities=activities_list, classes=classes_list,
                           unread_notifications_count=unread_notifications_count)


@teacher_bp.route('/create_activity', methods=['POST'])
def create_activity():
    if 'username' not in session or session.get('role') != 'teacher':
        return jsonify({'error': 'Unauthorized access'}), 401

    try:
        #  Basic form fields
        class_id = request.form.get('class_id')
        if not class_id:
            return jsonify({'error': 'Class is required'}), 400

        title = request.form['title']
        description = request.form['description']
        instructions = request.form['instructions']
        starter_code = request.form.get('starter_code', '')
        due_date = datetime.strptime(request.form['due_date'], '%Y-%m-%dT%H:%M')
        created_at = datetime.now()

        # Get rubrics arrays from form
        rubric_names = request.form.getlist('rubric_name[]')
        rubric_weights = request.form.getlist('rubric_weight[]')

        if not rubric_names or not rubric_weights:
            return jsonify({'error': 'Rubrics are required'}), 400

        rubrics = {}
        for name, weight in zip(rubric_names, rubric_weights):
            rubrics[name.strip()] = int(weight)

        required_rubrics = ["Correctness", "Syntax", "Logic", "Similarity"]
        for r in required_rubrics:
            if r not in rubrics:
                return jsonify({'error': f'Missing rubric: {r}'}), 400

        correctness_weight = rubrics.get("Correctness", 0)
        syntax_weight = rubrics.get("Syntax", 0)
        logic_weight = rubrics.get("Logic", 0)
        similarity_weight = rubrics.get("Similarity", 0)

        #  Validate weights sum = 100
        total_weight = correctness_weight + syntax_weight + logic_weight + similarity_weight
        if total_weight != 100:
            return jsonify({'error': 'Rubric weights must sum to 100%'}), 400

        #  Get teacher ID
        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
        teacher_row = cur.fetchone()
        teacher_id = teacher_row['id']

        # Verify teacher owns the class
        cur.execute("SELECT id FROM classes WHERE id=%s AND teacher_id=%s", (class_id, teacher_id))
        if not cur.fetchone():
            return jsonify({'error': 'Unauthorized access to class'}), 403

        # Insert into DB
        cur.execute("""
            INSERT INTO activities (
                teacher_id, class_id, title, description, instructions,
                starter_code, due_date, correctness_weight,
                syntax_weight, logic_weight, similarity_weight, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            teacher_id, class_id, title, description, instructions,
            starter_code, due_date, correctness_weight,
            syntax_weight, logic_weight, similarity_weight, created_at
        ))

        # Get the last inserted activity ID
        cur.execute("SELECT LAST_INSERT_ID()")
        activity_id_row = cur.fetchone()
        activity_id = activity_id_row['LAST_INSERT_ID()']

        # Notify students about the new activity
        notify_students_activity_assigned(class_id, activity_id, title, due_date)

        mysql.connection.commit()

        return jsonify({'success': 'Activity created successfully'}), 201


    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if 'cur' in locals():
            cur.close()


@teacher_bp.route('/activity/<int:activity_id>', methods=['GET', 'PUT', 'DELETE'])
def manage_activity(activity_id):
    if 'username' not in session or session.get('role') != 'teacher':
        return jsonify({'error': 'Unauthorized access'}), 401
    
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    try:
        cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
        teacher_row = cur.fetchone()
        if not teacher_row:
            return jsonify({'error': 'Teacher not found'}), 404
        teacher_id = teacher_row['id']
        
        if request.method == 'GET':
            # Get activity details
            cur.execute("""
                SELECT a.id, a.teacher_id, a.class_id, a.title, a.description, a.instructions,
                        a.starter_code, a.due_date, a.correctness_weight, a.syntax_weight,
                        a.logic_weight, a.similarity_weight, a.created_at,
                        COUNT(s.id) AS submission_count, c.name AS class_name
                FROM activities a
                LEFT JOIN submissions s ON a.id = s.activity_id
                LEFT JOIN classes c ON a.class_id = c.id
                WHERE a.id = %s AND a.teacher_id = %s
                GROUP BY a.id
            """, (activity_id, teacher_id))

            activity = cur.fetchone()
            if not activity:
                return jsonify({'error': 'Activity not found'}), 404


            class_name = activity['class_name']
            if activity['class_id'] is None:
                class_name = 'No Class'
            elif class_name is None:
                class_name = 'Class Deleted'
            elif class_name == '':
                class_name = 'Unnamed Class'
            # else keep class_name

            activity_dict = {
                'id': activity['id'],
                'teacher_id': activity['teacher_id'],
                'class_id': activity['class_id'],
                'title': activity['title'],
                'description': activity['description'],
                'instructions': activity['instructions'],
                'starter_code': activity['starter_code'],
                'due_date': activity['due_date'].strftime('%Y-%m-%d %H:%M:%S') if activity['due_date'] else None,
                'correctness_weight': activity['correctness_weight'],
                'syntax_weight': activity['syntax_weight'],
                'logic_weight': activity['logic_weight'],
                'similarity_weight': activity['similarity_weight'],
                'created_at': activity['created_at'].strftime('%Y-%m-%d %H:%M:%S') if activity['created_at'] else None,
                'submission_count': activity['submission_count'],
                'class_name': class_name
            }

            return jsonify(activity_dict)
        
        elif request.method == 'PUT':
            # Get form data
            class_id = request.form.get('class_id')
            title = request.form['title']
            description = request.form['description']
            instructions = request.form['instructions']
            starter_code = request.form.get('starter_code', '')
            due_date = datetime.strptime(request.form['due_date'], '%Y-%m-%dT%H:%M')

            # Get rubrics arrays from form
            rubric_names = request.form.getlist('rubric_name[]')
            rubric_weights = request.form.getlist('rubric_weight[]')

            if not rubric_names or not rubric_weights:
                return jsonify({'error': 'Rubrics are required'}), 400


            rubrics = {}
            for name, weight in zip(rubric_names, rubric_weights):
                rubrics[name.strip()] = int(weight)

            required_rubrics = ["Correctness", "Syntax", "Logic", "Similarity"]
            for r in required_rubrics:
                if r not in rubrics:
                    return jsonify({'error': f'Missing rubric: {r}'}), 400

            correctness_weight = rubrics.get("Correctness", 0)
            syntax_weight = rubrics.get("Syntax", 0)
            logic_weight = rubrics.get("Logic", 0)
            similarity_weight = rubrics.get("Similarity", 0)

            # Validate weights sum = 100
            total_weight = correctness_weight + syntax_weight + logic_weight + similarity_weight
            if total_weight != 100:
                return jsonify({'error': 'Rubric weights must sum to 100%'}), 400

            # If class_id is provided and not empty, verify teacher owns the new class
            if class_id and class_id.strip():
                cur.execute("SELECT id FROM classes WHERE id=%s AND teacher_id=%s", (class_id, teacher_id))
                if not cur.fetchone():
                    return jsonify({'error': 'Unauthorized access to class'}), 403

            # Update activity in database
            if class_id and class_id.strip():
                cur.execute("""
                    UPDATE activities
                    SET class_id=%s, title=%s, description=%s, instructions=%s, starter_code=%s,
                        due_date=%s, correctness_weight=%s, syntax_weight=%s,
                        logic_weight=%s, similarity_weight=%s
                    WHERE id=%s AND teacher_id=%s
                """, (
                    class_id, title, description, instructions, starter_code, due_date,
                    correctness_weight, syntax_weight, logic_weight, similarity_weight,
                    activity_id, teacher_id
                ))
            else:
                cur.execute("""
                    UPDATE activities
                    SET class_id=NULL, title=%s, description=%s, instructions=%s, starter_code=%s,
                        due_date=%s, correctness_weight=%s, syntax_weight=%s,
                        logic_weight=%s, similarity_weight=%s
                    WHERE id=%s AND teacher_id=%s
                """, (
                    title, description, instructions, starter_code, due_date,
                    correctness_weight, syntax_weight, logic_weight, similarity_weight,
                    activity_id, teacher_id
                ))

            mysql.connection.commit()
            return jsonify({'success': 'Activity updated successfully'})
            
        elif request.method == 'DELETE':
            # Check if activity exists and belongs to teacher
            cur.execute("SELECT id FROM activities WHERE id=%s AND teacher_id=%s", (activity_id, teacher_id))
            activity = cur.fetchone()
            
            if not activity:
                return jsonify({'error': 'Activity not found'}), 404
            
            # Delete activity
            cur.execute("DELETE FROM activities WHERE id=%s", (activity_id,))
            mysql.connection.commit()
            
            return jsonify({'success': 'Activity deleted successfully'})
            
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'error': str(e)}), 500
        
    finally:
        if 'cur' in locals():
            cur.close()
    

    
@teacher_bp.route('/classes')
def teacherClasses():
    if 'username' not in session or session.get('role') != 'teacher':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))
    
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Get unread notifications count
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    teacher_id = cur.fetchone()['id']
    unread_notifications_count = get_unread_notifications_count(teacher_id)

    # Get all classes created by this teacher
    cur.execute("""
        SELECT c.id, c.name, c.description, c.class_code, c.code_expires, 
                COUNT(e.student_id) as student_count
        FROM classes c
        LEFT JOIN enrollments e ON c.id = e.class_id
        WHERE c.teacher_id = %s
        GROUP BY c.id
        ORDER BY c.created_at DESC
    """, (teacher_id,))
    
    classes = cur.fetchall()
    
    # Get activities count for each class
    classes_list = []
    for class_item in classes:
        cur.execute("SELECT COUNT(*) FROM activities WHERE class_id=%s", (class_item['id'],))
        activity_count = cur.fetchone()['COUNT(*)']

        classes_list.append({
            'id': class_item['id'],
            'name': class_item['name'],
            'description': class_item['description'],
            'class_code': class_item['class_code'],
            'code_expires': class_item['code_expires'],
            'student_count': class_item['student_count'],
            'activity_count': activity_count
        })
    
    cur.close()
    
    return render_template('teacher_classes.html', classes=classes_list, first_name=session['first_name'],
                           unread_notifications_count=unread_notifications_count)


@teacher_bp.route('/create_class', methods=['POST'])
def create_class():
    if 'username' not in session or session.get('role') != 'teacher':
        return jsonify({'error': 'Unauthorized access'}), 401
    
    try:
        name = request.form['name']
        description = request.form.get('description', '')
        
        # Generate a unique class code
        import random
        import string
        from datetime import datetime, timedelta
        
        # Generate a 6-character alphanumeric code
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        code_expires = datetime.now() + timedelta(days=7)  # Code expires in 7 days
        
        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        #  Get teacher ID
        cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
        teacher_id = cur.fetchone()['id']
        
        # Insert new class
        cur.execute("""
            INSERT INTO classes (teacher_id, name, description, class_code, code_expires)
            VALUES (%s, %s, %s, %s, %s)
        """, (teacher_id, name, description, code, code_expires))
        
        mysql.connection.commit()
        cur.close()
        
        return jsonify({
            'success': 'Class created successfully!',
            'class_code': code,
            'expires': code_expires.strftime('%Y-%m-%d %H:%M:%S')
        }), 200
        
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'error': str(e)}), 500


@teacher_bp.route('/class/<int:class_id>/regenerate_code', methods=['POST'])
def regenerate_class_code(class_id):
    if 'username' not in session or session.get('role') != 'teacher':
        return jsonify({'error': 'Unauthorized access'}), 401
    
    try:

        import random
        import string
        from datetime import datetime, timedelta
        
        new_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        new_expires = datetime.now() + timedelta(days=7)
        
        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        
        # Verify the teacher owns this class
        cur.execute("SELECT teacher_id FROM classes WHERE id=%s", (class_id,))
        class_info = cur.fetchone()
        
        if not class_info:
            return jsonify({'error': 'Class not found'}), 404
        
        cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
        teacher_id = cur.fetchone()['id']
        
        if class_info['teacher_id'] != teacher_id:
            return jsonify({'error': 'Unauthorized access'}), 403
        
        # Update the class code
        cur.execute("""
            UPDATE classes 
            SET class_code=%s, code_expires=%s 
            WHERE id=%s
        """, (new_code, new_expires, class_id))
        
        mysql.connection.commit()
        cur.close()
        
        return jsonify({
            'success': 'Class code regenerated!',
            'class_code': new_code,
            'expires': new_expires.strftime('%Y-%m-%d %H:%M:%S')
        }), 200
        
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'error': str(e)}), 500


@teacher_bp.route('/class/<int:class_id>')
def view_class(class_id):
    if 'username' not in session or session.get('role') != 'teacher':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))
    
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Get unread notifications count
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    teacher_id = cur.fetchone()['id']
    unread_notifications_count = get_unread_notifications_count(teacher_id)
    
    # Verify the teacher owns this class
    cur.execute("SELECT teacher_id FROM classes WHERE id=%s", (class_id,))
    class_info = cur.fetchone()
    
    if not class_info:
        flash('Class not found', 'error')
        return redirect(url_for('teacher.teacherClasses'))
    
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    teacher_id = cur.fetchone()['id']
    
    if class_info['teacher_id'] != teacher_id:
        flash('Unauthorized access', 'error')
        return redirect(url_for('teacher.teacherClasses'))
    
    # Get class details
    cur.execute("""
        SELECT c.id, c.name, c.description, c.class_code, c.code_expires, c.created_at
        FROM classes c
        WHERE c.id = %s
    """, (class_id,))
    
    class_data = cur.fetchone()
    
    # Get enrolled students
    cur.execute("""
        SELECT u.id, u.username, u.first_name, u.last_name, e.enrolled_at
        FROM enrollments e
        JOIN users u ON e.student_id = u.id
        WHERE e.class_id = %s
        ORDER BY u.first_name, u.last_name
    """, (class_id,))
    
    students = cur.fetchall()
    
    # Get class activities
    cur.execute("""
        SELECT id, title, due_date, created_at
        FROM activities
        WHERE class_id = %s
        ORDER BY due_date ASC
    """, (class_id,))
    
    activities = cur.fetchall()
    
    cur.close()
    
    class_dict = {
        'id': class_data['id'],
        'name': class_data['name'],
        'description': class_data['description'],
        'class_code': class_data['class_code'],
        'code_expires': class_data['code_expires'],
        'created_at': class_data['created_at']
    }
    
    students_list = []
    for student in students:
        students_list.append({
            'id': student['id'],
            'username': student['username'],
            'first_name': student['first_name'],
            'last_name': student['last_name'],
            'enrolled_at': student['enrolled_at']
        })

    activities_list = []
    for activity in activities:
        activities_list.append({
            'id': activity['id'],
            'title': activity['title'],
            'due_date': activity['due_date'],
            'created_at': activity['created_at']
        })

    unread_notifications_count = session.pop('unread_notifications_count', None)


    
    return render_template('teacher_class_view.html',
                            class_data=class_dict,
                            students=students_list,
                            activities=activities_list,
                            first_name=session['first_name'],
                            unread_notifications_count=unread_notifications_count)

# New route to delete enrolled students
@teacher_bp.route('/class/<int:class_id>/delete_students', methods=['POST'])
def delete_enrolled_students(class_id):
    if 'username' not in session or session.get('role') != 'teacher':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    student_ids = request.form.getlist('student_ids')
    if not student_ids:
        flash('No students selected for deletion.', 'error')
        return redirect(url_for('teacher.view_class', class_id=class_id))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Get unread notifications count
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    teacher_id = cur.fetchone()['id']
    unread_notifications_count = get_unread_notifications_count(teacher_id)

    # Verify the teacher owns this class
    cur.execute("SELECT teacher_id FROM classes WHERE id=%s", (class_id,))
    class_info = cur.fetchone()
    if not class_info:
        flash('Class not found', 'error')
        cur.close()
        return redirect(url_for('teacher.teacherClasses'))

    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    teacher_id = cur.fetchone()['id']

    if class_info['teacher_id'] != teacher_id:
        flash('Unauthorized access', 'error')
        cur.close()
        return redirect(url_for('teacher.teacherClasses'))
    
    cur.execute("SELECT name FROM classes WHERE id=%s", (class_id,))
    class_name_row = cur.fetchone()
    if class_name_row:
        class_name = class_name_row['name']
    else:
        class_name = "the class"

    try:
        # Delete enrollments for selected students in this class
        format_strings = ','.join(['%s'] * len(student_ids))
        query = f"DELETE FROM enrollments WHERE class_id=%s AND student_id IN ({format_strings})"
        cur.execute(query, [class_id] + student_ids)

        # Insert notifications for each removed student
        notification_query = """
            INSERT INTO notifications (user_id, role, type, message, link, is_read, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """
        for student_id in student_ids:
            message = f'You have been removed from class {class_name} by your teacher.'
            link = url_for('student.studentClasses')  # or any relevant link
            cur.execute(notification_query, (student_id, 'student', 'removed_from_class', message, link, False))

        mysql.connection.commit()
        flash(f'Successfully deleted {len(student_ids)} student(s) from the class.', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Failed to delete students: {str(e)}', 'error')
    finally:
        cur.close()

    session['unread_notifications_count'] = unread_notifications_count

    return redirect(url_for('teacher.view_class', class_id=class_id))
    
    


@teacher_bp.route('/delete_class/<int:class_id>', methods=['POST'])
def delete_class(class_id):
    if 'username' not in session or session.get('role') != 'teacher':
        return jsonify({'error': 'Unauthorized access'}), 401

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    try:
        # Verify the teacher owns this class
        cur.execute("SELECT teacher_id FROM classes WHERE id=%s", (class_id,))
        class_info = cur.fetchone()
        if not class_info:
            return jsonify({'error': 'Class not found'}), 404

        cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
        teacher_id = cur.fetchone()['id']

        if class_info['teacher_id'] != teacher_id:
            return jsonify({'error': 'Unauthorized access'}), 403
        
        # Get all students enrolled in the class
        cur.execute("SELECT student_id FROM enrollments WHERE class_id=%s", (class_id,))
        students = cur.fetchall()
        student_ids = [row[0] for row in students]

        # Get class name
        cur.execute("SELECT name FROM classes WHERE id=%s", (class_id,))
        class_name_row = cur.fetchone()
        class_name = class_name_row['name'] if class_name_row else "the class"

        # Notify students about class deletion
        notification_query = """
            INSERT INTO notifications (user_id, role, type, message, link, is_read, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """
        for student_id in student_ids:
            message = f'The class "{class_name}" has been deleted by your teacher.'
            link = url_for('student.studentClasses')
            cur.execute(notification_query, (student_id, 'student', 'class_deleted', message, link, False))

        # Delete submissions for activities in this class
        cur.execute("""
            DELETE s FROM submissions s
            INNER JOIN activities a ON s.activity_id = a.id
            WHERE a.class_id = %s
        """, (class_id,))

        # Delete activities for this class
        cur.execute("DELETE FROM activities WHERE class_id=%s", (class_id,))

        # Delete enrollments for this class
        cur.execute("DELETE FROM enrollments WHERE class_id=%s", (class_id,))

        # Delete the class
        cur.execute("DELETE FROM classes WHERE id=%s", (class_id,))

        mysql.connection.commit()

        return jsonify({'success': 'Class and all associated activities deleted successfully'}), 200

    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()




@teacher_bp.route('/settings', methods=['GET', 'POST'])
def teacherSettings():
    if 'username' not in session or session.get('role') != 'teacher':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Get unread notifications count
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    teacher_row = cur.fetchone()
    if not teacher_row:
        flash('User not found', 'error')
        return redirect(url_for('auth.login'))
    teacher_id = teacher_row['id']
    unread_notifications_count = get_unread_notifications_count(teacher_id)

    cur.execute("SELECT * FROM users WHERE username = %s", (session['username'],))
    user = cur.fetchone()

    if request.method == 'POST':
        # Profile info
        username = request.form.get('username', '').strip()
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip()
        if email == '':
            email = None

        # Password change fields
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        # Validate required profile fields
        if not username or not first_name or not last_name:
            flash('Username, First name, and Last name, are required.', 'error')
            return render_template('teacher_settings.html', user=user, unread_notifications_count=unread_notifications_count)

        # Check if the new username is already taken by another user
        cur.execute("SELECT username FROM users WHERE username = %s AND username != %s", (username, session['username']))
        existing_user = cur.fetchone()

        if existing_user:
            errors = {}
            # After checking if username exists
            if existing_user:
                errors['username'] = 'The username is already taken. Please choose a different one.'
            # Then, if errors exist, render template with errors and user data
            if errors:
                return render_template('teacher_settings.html', user=user, errors=errors, unread_notifications_count=unread_notifications_count)


        # Password change validation
        if new_password or confirm_password:
            if not current_password:
                flash('Current password is required to change password.', 'error')
                return render_template('teacher_settings.html', user=user, unread_notifications_count=unread_notifications_count)
            if not check_password_hash(user['password'], current_password):
                flash('Current password is incorrect.', 'error')
                return render_template('teacher_settings.html', user=user, unread_notifications_count=unread_notifications_count)
            if new_password != confirm_password:
                flash('New password and confirmation do not match.', 'error')
                return render_template('teacher_settings.html', user=user, unread_notifications_count=unread_notifications_count)
            if len(new_password) < 6:
                flash('New password must be at least 6 characters.', 'error')
                return render_template('teacher_settings.html', user=user, unread_notifications_count=unread_notifications_count)
            hashed_password = generate_password_hash(new_password)
        else:
            hashed_password = user['password']

        # Check if any changes were made
        changed = (
            username != user['username'] or
            first_name != user['first_name'] or
            last_name != user['last_name'] or
            email != user['email'] or
            hashed_password != user['password']
        )

        if not changed:
            if request.headers.get('Accept') == 'application/json':
                return jsonify({'info': 'No changes detected'})
            else:
                flash('No changes detected.', 'info')
                return redirect(url_for('teacher.teacherSettings'))

        # Use a separate cursor for the update to avoid cursor state issues
        update_cur = mysql.connection.cursor()
        try:
            update_cur.execute("""
                UPDATE users
                SET username=%s, first_name=%s, last_name=%s, email=%s, password=%s
                WHERE username=%s
            """, (
                username, first_name, last_name, email, hashed_password,
                session['username']
            ))
            mysql.connection.commit()

            # Update session info
            session['username'] = username
            session['first_name'] = first_name
            session['last_name'] = last_name

            if request.headers.get('Accept') == 'application/json':
                return jsonify({'success': 'Settings updated successfully'})
            else:
                flash('Settings updated successfully.', 'success')
                return redirect(url_for('teacher.teacherSettings'))
        except Exception as e:
            mysql.connection.rollback()
            flash(f'Failed to update settings: {str(e)}', 'error')
        finally:
            update_cur.close()

    cur.close()
    return render_template('teacher_settings.html', user=user,
                            unread_notifications_count=unread_notifications_count)

def get_unread_notifications_count(user_id):
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM notifications
        WHERE user_id = %s AND role = 'teacher' AND is_read = FALSE
    """, (user_id,))
    result = cur.fetchone()
    cur.close()
    return result['COUNT(*)'] if result else 0

def add_notification(user_id, role, notif_type, message, link=None):
    user_id = int(user_id)
    cur = mysql.connection.cursor()
    cur.execute("""
        INSERT INTO notifications (user_id, role, `type`, message, link, is_read, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
    """, (user_id, role, notif_type, message, link, False))
    mysql.connection.commit()
    cur.close()

def notify_students_activity_assigned(class_id, activity_id, activity_title, due_date):
    cur = mysql.connection.cursor()
    cur.execute("SELECT student_id FROM enrollments WHERE class_id = %s", (class_id,))
    students = cur.fetchall()
    for (student_id,) in students:
        message = f"New activity assigned: '{activity_title}' in your class. Deadline: {due_date.strftime('%b').upper()} {due_date.strftime('%d, %Y')}."
        link = url_for('student.viewActivity', activity_id=activity_id)
        cur.execute("""
            INSERT INTO notifications (user_id, role, type, message, link, is_read, created_at)
            VALUES (%s, 'student', 'new_activity', %s, %s, %s, NOW())
        """, (student_id, message, link, False))
    mysql.connection.commit()
    cur.close()

def notify_teacher_activity_finished(teacher_id, activity_title, class_name, total_submissions, total_students):
    message = (f"Activity '{activity_title}' in class '{class_name}' is finished. "
                f"Submissions: {total_submissions}/{total_students}.")
    add_notification(teacher_id, 'teacher', 'activity_finished', message)

def notify_finished_activities():
    cur = mysql.connection.cursor()

    # Find activities where:
    # - due date passed OR all students submitted
    # - AND notified_finished = FALSE (not notified yet)
    cur.execute("""
        SELECT a.id, a.title, a.class_id, c.teacher_id, c.name
        FROM activities a
        JOIN classes c ON a.class_id = c.id
        WHERE a.notified_finished = FALSE
        AND (
            a.due_date < NOW()
            OR (
                SELECT COUNT(*) FROM enrollments e WHERE e.class_id = a.class_id
            ) = (
                SELECT COUNT(DISTINCT s.student_id) FROM submissions s WHERE s.activity_id = a.id
            )
        )
    """)
    activities = cur.fetchall()

    for activity in activities:
        activity_id = activity['id']
        title = activity['title']
        class_id = activity['class_id']
        teacher_id = activity['teacher_id']
        class_name = activity['name']
        if teacher_id is None:
            continue
        # Count total students in class
        cur.execute("SELECT COUNT(*) FROM enrollments WHERE class_id = %s", (class_id,))
        total_students = cur.fetchone()['COUNT(*)']

        # Count total submissions for activity
        cur.execute("SELECT COUNT(DISTINCT student_id) FROM submissions WHERE activity_id = %s", (activity_id,))
        total_submissions = cur.fetchone()['COUNT(DISTINCT student_id)']

        notify_teacher_activity_finished(teacher_id, title, class_name, total_submissions, total_students)

        # Mark activity as notified
        cur.execute("UPDATE activities SET notified_finished = TRUE WHERE id = %s", (activity_id,))

    mysql.connection.commit()
    cur.close()



@teacher_bp.route('/notifications')
def notifications():
    if 'username' not in session or session.get('role') != 'teacher':
        flash('Unauthorized access', 'error')
        return redirect(url_for('auth.login'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
    user = cur.fetchone()
    if not user:
        flash('User  not found', 'error')
        return redirect(url_for('auth.login'))
    teacher_id = user['id']

    cur.execute("""
        SELECT id, type, message, link, is_read, created_at
        FROM notifications
        WHERE user_id = %s AND role = 'teacher'
        ORDER BY created_at DESC
    """, (teacher_id,))
    notifications = cur.fetchall()

    cur.execute("""
        UPDATE notifications SET is_read = TRUE
        WHERE user_id = %s AND role = 'teacher' AND is_read = FALSE
    """, (teacher_id,))
    mysql.connection.commit()
    cur.close()

    return render_template('teacher_notifications.html', notifications=notifications, username=session['username'])

@teacher_bp.route('/delete_submission/<int:submission_id>', methods=['POST'])
def delete_submission(submission_id):
    if 'username' not in session or session.get('role') != 'teacher':
        return jsonify({'error': 'Unauthorized access'}), 401

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    try:
        # Get teacher ID
        cur.execute("SELECT id FROM users WHERE username=%s", (session['username'],))
        teacher_row = cur.fetchone()
        if not teacher_row:
            return jsonify({'error': 'Teacher not found'}), 404
        teacher_id = teacher_row['id']

        # Fetch submission details to verify existence, ownership, and get student_id/activity_title
        cur.execute("""
            SELECT s.id, s.student_id, a.id as activity_id, a.title as activity_title,
                   a.teacher_id, c.id as class_id, c.teacher_id as class_teacher_id
            FROM submissions s
            JOIN activities a ON s.activity_id = a.id
            JOIN classes c ON a.class_id = c.id
            WHERE s.id = %s
        """, (submission_id,))

        submission = cur.fetchone()

        if not submission:
            return jsonify({'error': 'Submission not found'}), 404

        student_id = submission['student_id']
        activity_id = submission['activity_id']
        activity_title = submission['activity_title']

        # Verify teacher owns the activity (direct via activities.teacher_id) or class (via classes.teacher_id)
        if submission['teacher_id'] != teacher_id and submission['class_teacher_id'] != teacher_id:
            return jsonify({'error': 'Not authorized to delete this submission'}), 403

        # Delete the submission
        cur.execute("DELETE FROM submissions WHERE id = %s", (submission_id,))
        
        # Send notification to the student
        message = f"Your submission for '{activity_title}' has been deleted by your teacher. You can now resubmit it."
        link = url_for('student.viewActivity', activity_id=activity_id)  # Internal URL for link
        cur.execute("""
            INSERT INTO notifications (user_id, role, type, message, link, is_read, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """, (student_id, 'student', 'submission_deleted', message, link, False))
        
        mysql.connection.commit()

        return jsonify({'message': 'Submission deleted successfully. The activity is now available for resubmission.'})

    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()


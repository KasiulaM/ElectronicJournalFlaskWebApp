import sqlite3
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import base64
from io import BytesIO
from flask import Flask, render_template, request, flash, redirect, url_for, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash 
from models import DatabaseOperations
from datetime import datetime, timedelta, timezone
from statistics import median, mode

# Substring function to check that provided email is correct for each role in Adding New User page.
def mid(string, dotmail):
    return string[len(string)-len(dotmail):len(string)]

# Function to check that name and surname is written in correct convention (first letter uppercase, other lowercase)
def check_word(word):
    return word[0].isupper() and word[1:].islower()

# Creating the flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'MiszkielMocio'

# Automatic logout after 5 minutes of no activity
timeout_duration = timedelta(minutes=5)

# If user do any action, last activity is current time
def update_last_activity():
    session['last_activity'] = datetime.now(timezone.utc)

# if last activity was over 5 minutes ago, returns True, if not returns False
def is_session_expired():
    last_activity = session.get('last_activity')
    if last_activity:
        last_activity_utc = last_activity.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - last_activity_utc > timeout_duration
    return False

login_manager = LoginManager()
login_manager.init_app(app)

# Make a connection with database and create cursor 
conn = sqlite3.connect("school_database.db", check_same_thread=False)
cursor = conn.cursor()

# Connection with class in models.py to do specific operations
operation = DatabaseOperations(cursor, conn)
operation.generate_database() # if not exist, create database
operation.add_data() # if tables empty add dataset, uncomment data in models.py and comment empty data lists above data

# Loading active user to python memory
class User(UserMixin):
    pass
@login_manager.user_loader
def load_user(user_id):
    user = User()
    try:
        (user.id, user.email, user.first_name, user.second_name, user.password, user.role) = cursor.execute(f"""
        SELECT id, email, first_name, second_name, password, role FROM user WHERE id='{user_id}'""").fetchone()
    except TypeError:
        user = None
    return user

# Basic link to the local host opens welcome page
@app.route('/')
def welcome():
    return render_template("welcome.html")

@app.route('/student_dashboard', methods=['GET', 'POST'])
@login_required
def student_dashboard():
    # Check if the user is a student
    if current_user.role == 'student':
        # Check if the session is expired
        if is_session_expired():
            return redirect(url_for('logout'))
        
        update_last_activity()  # The latest page refresh

        # Get information about the class to which the student is assigned
        class_info = cursor.execute(f'''SELECT c.id, c.name, c.profile
                                        FROM class c
                                        JOIN student s ON c.id = s.class_id
                                        WHERE s.id = {current_user.id}''').fetchone()

        # Get the number of students in the class
        num_students = cursor.execute(f'SELECT COUNT(*) FROM student WHERE class_id = {class_info[0]}').fetchone()[0]

        # Get the subjects to which the student is enrolled
        subjects = cursor.execute(f'''SELECT s.id, s.name
                                      FROM subject s
                                      JOIN teacher_class tc ON s.id = tc.subject_id
                                      JOIN student st ON st.class_id = tc.class_id
                                      WHERE st.id = {current_user.id}''').fetchall()

        # Sort subjects alphabetically
        subjects = sorted(subjects, key=lambda x: x[1])

        # Get the information about the student's latest grade
        latest_grade_info = cursor.execute(f'''SELECT g.value, s.name AS subject_name, 
                                                  (u.first_name || ' ' || u.second_name) AS teacher_name
                                               FROM grade g
                                               JOIN subject s ON g.subject_id = s.id
                                               JOIN teacher_class tc ON tc.subject_id = s.id 
                                               AND tc.class_id = (SELECT class_id FROM student WHERE id = {current_user.id})
                                               JOIN teacher t ON tc.teacher_id = t.id
                                               JOIN user u ON t.id = u.id
                                               WHERE g.student_id = {current_user.id}
                                               ORDER BY g.id DESC''').fetchone()

        # Get the grades of the student with weights
        grades = cursor.execute(f'''SELECT CAST(g.value AS INTEGER), g.weight
                                    FROM grade g
                                    WHERE g.student_id = {current_user.id}''').fetchall()

        # Calculate the weighted average of the student
        weighted_sum = sum(grade[0] * grade[1] for grade in grades)
        total_weight = sum(grade[1] for grade in grades)
        total_average = weighted_sum / total_weight if total_weight > 0 else 0

        # Get the class average grade list
        class_avg_list = cursor.execute(f'''SELECT s.id, 
                                                SUM(CAST(g.value AS INTEGER) * g.weight) / SUM(g.weight) AS avg_grade
                                            FROM student s
                                            JOIN grade g ON s.id = g.student_id
                                            WHERE s.class_id = {class_info[0]}
                                            GROUP BY s.id
                                            ORDER BY avg_grade DESC''').fetchall()

        # Find the position of the logged-in student in the list
        student_rank = next((i + 1 for i, (student_id, _) in enumerate(class_avg_list) if student_id == current_user.id), None)

        # DATA FOR CHART
        # Get student's grades from all subjects
        student_grades = cursor.execute(f'''SELECT s.name AS subject, 
                                              SUM(CAST(g.value AS INTEGER) * g.weight) / SUM(g.weight) AS avg_grade
                                           FROM grade g
                                           JOIN subject s ON g.subject_id = s.id
                                           WHERE g.student_id = {current_user.id}
                                           GROUP BY s.id
                                           ORDER BY avg_grade ASC''').fetchall()

        # Get the names of subjects and average grades
        subject_list = [student_grade[0] for student_grade in student_grades]
        avg_grade = [float(student_grade[1]) for student_grade in student_grades]

        # Clear the current plot before creating a new one
        plt.clf()

        # CREATING A PLOT
        plt.figure(figsize=(15, 5))
        plt.barh(subject_list, avg_grade, color='skyblue', edgecolor='black')
        plt.title('Average Grades per Subject')
        plt.xlabel('Average Grade')
        plt.ylabel('Subjects')
        for index, value in enumerate(avg_grade):
            plt.text(value + 0.1, index, f'{value:.2f}', ha='center', fontsize=10)

        # Save the plot as an image in base64 format
        buffer = BytesIO()
        plt.savefig(buffer, format='png')
        buffer.seek(0)
        plot_data_s = base64.b64encode(buffer.read()).decode('utf-8')

        # SELECTED SUBJECT SECTION
        selected_subject = None
        selected_subject_id = None
        subject_average = None
        class_subject_avg = None

        if request.method == 'POST':
            # Handle the selected subject from the form
            selected_subject_id = request.form.get('selected_subject')
            selected_subject = next((subject for subject in subjects if subject[0] == int(selected_subject_id)), None)

            # Get grades from the selected subject and calculate the average
            selected_subject_grades = cursor.execute(f'''SELECT CAST(g.value AS INTEGER), g.weight
                                                         FROM grade g
                                                         WHERE g.student_id = {current_user.id}
                                                         AND g.subject_id = {selected_subject_id}''').fetchall()

            # Calculate the weighted average from the selected subject
            weighted_sum_subject = sum(grade[0] * grade[1] for grade in selected_subject_grades)
            total_weight_subject = sum(grade[1] for grade in selected_subject_grades)
            subject_average = weighted_sum_subject / total_weight_subject if total_weight_subject > 0 else 0

            # Get grades of students from the selected subject in the class
            class_subject_grades = cursor.execute(f'''SELECT CAST(g.value AS INTEGER), g.weight
                                                      FROM grade g
                                                      JOIN student s ON g.student_id = s.id
                                                      WHERE s.class_id = {class_info[0]}
                                                      AND g.subject_id = {selected_subject[0]}''').fetchall()

            # Calculate the average grades of students from the selected subject in the class
            class_subject_weighted_sum = sum(grade[0] * grade[1] for grade in class_subject_grades)
            class_subject_total_weight = sum(grade[1] for grade in class_subject_grades)
            class_subject_avg = class_subject_weighted_sum / class_subject_total_weight if class_subject_total_weight > 0 else 0

        # Pass the results to the template
        return render_template("student_dashboard.html", user=current_user, num_students=num_students,
                               subjects=subjects, selected_subject_id=selected_subject_id,
                               selected_subject=selected_subject, latest_grade_info=latest_grade_info,
                               class_name=class_info[1], class_profile=class_info[2], total_average=total_average,
                               subject_average=subject_average, student_rank=student_rank,
                               class_subject_avg=class_subject_avg,plot_data_s=plot_data_s)
    elif current_user.role == 'teacher':
        return redirect(url_for('teacher_dashboard'))
    elif current_user.role == 'admin':
        return redirect(url_for('admin_panel'))
    elif not current_user.is_authenticated:
        return redirect(url_for('welcome'))

@app.route('/teacher_dashboard', methods=['GET', 'POST'])
@login_required
def teacher_dashboard():
    # Check if the user is a teacher
    if current_user.role == 'teacher':
        # Check if the session is expired
        if is_session_expired():
            return redirect(url_for('logout'))
        
        update_last_activity()  # The latest page refresh

        # Get information about the subject that the teacher teaches
        teacher_info = cursor.execute(f'''SELECT subject.id, subject.name
                                          FROM teacher
                                          JOIN subject ON teacher.subject_id = subject.id
                                          WHERE teacher.id = {current_user.id}''').fetchone()

        # Get the CLASSES that the teacher teaches
        classes_taught = cursor.execute(f'''SELECT c.id, c.name, c.profile
                                            FROM class c
                                            JOIN teacher_class tc ON c.id = tc.class_id
                                            WHERE tc.teacher_id = {current_user.id}''').fetchall()

        # Sort classes alphabetically
        classes_taught = sorted(classes_taught, key=lambda x: x[1])

        # SELECTED CLASS SECTION
        selected_class = None
        selected_class_id = None
        class_average = None
        class_median = None
        class_mode = None
        students_in_class = None
        highest_avg_student = None
        lowest_avg_student = None

        if request.method == 'POST':
            # Handle the selected class from the form
            selected_class_id = request.form.get('selected_class')
            selected_class = next((class_taught for class_taught in classes_taught if class_taught[0] == int(selected_class_id)), None)

            # Get grades for the selected class
            class_grades = cursor.execute(f'''SELECT CAST(g.value AS INTEGER), g.weight
                                              FROM grade g
                                              JOIN student s ON g.student_id = s.id
                                              WHERE s.class_id = {selected_class[0]}''').fetchall()

            # Calculate the average grades for the class
            weighted_sum_class = sum(grade[0] * grade[1] for grade in class_grades)
            total_weight_class = sum(grade[1] for grade in class_grades)
            class_average = weighted_sum_class / total_weight_class if total_weight_class > 0 else 0

            class_grades_values = [grade[0] for grade in class_grades]
            # Calculate the median grades for the class
            class_median = median(class_grades_values)
            # Calculate the mode grades for the class
            class_mode = mode(class_grades_values)

            # Get the list of students in the selected class
            students_in_class = cursor.execute(f'''SELECT u.id, u.first_name, u.second_name
                                                   FROM user u
                                                   JOIN student s ON u.id = s.id
                                                   WHERE s.class_id = {selected_class[0]}''').fetchall()
            students_in_class = sorted(students_in_class, key=lambda x: x[1])

            # Query for students ranking based on average grades
            students_rank = cursor.execute(f'''SELECT u.id, u.first_name, u.second_name, 
                                                  SUM(CAST(g.value AS INTEGER) * g.weight) / SUM(g.weight) AS avg_grade
                                               FROM user u
                                               JOIN student s ON u.id = s.id
                                               LEFT JOIN grade g ON g.student_id = s.id
                                               WHERE s.class_id = {selected_class[0]} AND g.subject_id = {teacher_info[0]}
                                               GROUP BY u.id
                                               ORDER BY avg_grade DESC''').fetchall()

            if students_rank:
                highest_avg_student = students_rank[0]
                lowest_avg_student = students_rank[-1]

                # Get the names of students
                student_names = [f"{student[1]} {student[2]}" for student in students_rank]

                # Transform grades to float type
                avg_grades = [float(student[3]) for student in students_rank]

                # Clear the current plot before creating a new one
                plt.clf()

                # CREATING A PLOT
                plt.figure(figsize=(15, 10))
                bars = plt.bar(student_names, avg_grades, color='skyblue', width=0.5, edgecolor='black')
                plt.xticks([])
                plt.title(f"Grades Bar Chart - class {selected_class[1]}", fontsize=16, weight='bold')
                plt.xlabel("Students")
                plt.ylabel("Average Grades")
                plt.ylim(0, 6.49)
                
                for bar, grade, student_name in zip(bars, avg_grades, student_names):
                    plt.text(bar.get_x() + bar.get_width() / 2 - 0.1, bar.get_height() + 0.1, f'{grade:.2f}',
                             ha='center', color='black')
                    # Add student name on the bar
                    plt.text(bar.get_x() + bar.get_width() / 2, 0.09, f'{student_name}', ha='center', color='black',
                             rotation=90, fontsize=10)

                # Save the plot as an image in base64 format
                buffer = BytesIO()
                plt.savefig(buffer, format='png')
                buffer.seek(0)
                plot_data_t = base64.b64encode(buffer.read()).decode('utf-8')

            return render_template("teacher_dashboard.html", user=current_user, subject_name=teacher_info[1],
                                   classes_taught=classes_taught, selected_class_id=selected_class_id,
                                   selected_class=selected_class, class_average=class_average,
                                   class_median=class_median, class_mode=class_mode,
                                   students_in_class=students_in_class, plot_data_t=plot_data_t,
                                   highest_avg_student=highest_avg_student, lowest_avg_student=lowest_avg_student)
        else:
            return render_template("teacher_dashboard.html", user=current_user, subject_name=teacher_info[1],
                                   classes_taught=classes_taught)
    elif current_user.role == 'student':
        return redirect(url_for('student_dashboard'))
    elif current_user.role == 'admin':
        return redirect(url_for('admin_panel'))
    elif not current_user.is_authenticated:
        return redirect(url_for('welcome'))

@app.route('/admin_panel')
@login_required
def admin_panel():
    if current_user.role == 'admin':
        if is_session_expired():
            return redirect(url_for('logout'))
        update_last_activity() # The latest page refresh
        operation.create_views() # Refreshing the views every time the admin panel is opened
        # Taking all from views
        vuser = cursor.execute('SELECT * FROM vw_users').fetchall()
        vsubject = cursor.execute('SELECT * FROM vw_subjects').fetchall()
        vclass = cursor.execute('SELECT * FROM vw_classes').fetchall()
        vgrade = cursor.execute('SELECT * FROM vw_grades').fetchall()
        vassign = cursor.execute('SELECT * FROM vw_assigns').fetchall()
        return render_template("admin_panel.html", user = current_user, vuser = vuser, vsubject = vsubject, vclass = vclass, vgrade = vgrade, vassign = vassign)
    
    elif current_user.role == 'student':
        return redirect(url_for('student_dashboard'))
    elif current_user.role == 'teacher':
        return redirect(url_for('teacher_dashboard'))
    elif not current_user.is_authenticated:
        return redirect(url_for('welcome'))

@app.route('/login_student', methods=['GET', 'POST'])
def login_student():
    if request.method == 'POST': # After submiting entered values
        # Get email and password from page
        email = request.form.get('email')
        password = request.form.get('password')
        # check that user exists in database
        user_data = cursor.execute("SELECT id, email, password, role FROM user WHERE email = ?", (email,)).fetchone()
        if user_data: # If exists
            if check_password_hash(user_data[2], password) and user_data[3] == 'student': # Check that password and role is correct
                flash('Logged in successfully!', category='success')
                # Login user to the journal
                user = load_user(user_data[0])
                login_user(user)
                return redirect(url_for('student_dashboard'))
            else:
                flash('Incorrect password or you are not a student, try again.', category='error')
                return redirect(url_for('login_student'))
        else:
            flash('Email does not exist.', category='error')
            return redirect(url_for('login_student'))

    return render_template("login_student.html", user=current_user)


@app.route('/login_teacher', methods=['GET', 'POST'])
def login_teacher():
    if request.method == 'POST': # After submiting entered values
        # Get email and password from page
        email = request.form.get('email')
        password = request.form.get('password')
        # check that user exists in database
        user_data = cursor.execute("SELECT id, email, password, role FROM user WHERE email = ?", (email,)).fetchone()
        if user_data: # If exists
            if check_password_hash(user_data[2], password) and user_data[3] == 'teacher': # Check that password and role is correct
                flash('Logged in successfully!', category='success')
                # Login user to the journal
                user = load_user(user_data[0])
                login_user(user)
                return redirect(url_for('teacher_dashboard'))
            else:
                flash('Incorrect password or you are not a teacher, try again.', category='error')
                return redirect(url_for('login_teacher'))
        else:
            flash('Email does not exist.', category='error')
            return redirect(url_for('login_teacher'))

    return render_template("login_teacher.html", user=current_user)

@app.route('/login_admin', methods=['GET', 'POST'])
def login_admin():
    if request.method == 'POST': # After submiting entered values
        # Get email and password from page
        email = request.form.get('email')
        password = request.form.get('password')
        # check that user exists in database
        user_data = cursor.execute("SELECT id, email, password, role FROM user WHERE email = ?", (email,)).fetchone()
        if user_data: # If exists
            if check_password_hash(user_data[2], password) and user_data[3] == 'admin': # Check that password and role is correct
                flash('Logged in successfully!', category='success')
                # Login user to the journal
                user = load_user(user_data[0])
                login_user(user)
                return redirect(url_for('admin_panel'))
            else:
                flash('Incorrect password or you are not an admin, try again.', category='error')
                return redirect(url_for('login_admin'))
        else:
            flash('Email does not exist.', category='error')
            return redirect(url_for('login_admin'))

    return render_template("login_admin.html", user=current_user)

@app.route('/logout')
@login_required
def logout():
    if current_user.role == 'student':
        logout_user() # Logout user from page
        session.clear() # Clear the latest activity
        flash("You're logged out.", 'message')
        return redirect(url_for('login_student'))
    elif current_user.role == 'teacher':
        logout_user() # Logout user from page
        session.clear() # Clear the latest activity
        flash("You're logged out.", 'message')
        return redirect(url_for('login_teacher'))
    elif current_user.role == 'admin':
        logout_user() # Logout user from page
        session.clear() # Clear the latest activity
        flash("You're logged out.", 'message')
        return redirect(url_for('login_admin'))
    
@app.route('/add_user', methods=['GET', 'POST'])
@login_required
def add_user():
    if current_user.role == 'admin':
        if is_session_expired():
            return redirect(url_for('logout'))
        update_last_activity() # The latest page refresh
        # Get all subjects and classes
        subjects = cursor.execute("SELECT id, name FROM subject").fetchall()
        classes = cursor.execute("SELECT id, name, profile FROM class").fetchall()
        if request.method == 'POST': # If values in page submitted
            role = request.form.get('role') # Selected role student/teacher
            email = request.form.get('email') # Written email
            firstname = request.form.get('firstName') # Written name
            secondname = request.form.get('secondName') # Written surname
            password = request.form.get('password') # Written password
            # Check that written email is correct for each role, using function mid written at the beginning of the code
            if role == 'student':
                if mid(email,'@student.uw.edu.pl') != '@student.uw.edu.pl':
                        flash('Invalid email. Must be @student.uw.edu.pl.', 'error')
                        return redirect(url_for('add_user'))
            elif role == 'teacher':
                if mid(email,'@uw.edu.pl') != '@uw.edu.pl':
                        flash('Invalid email. Must be @uw.edu.pl.', 'error')
                        return redirect(url_for('add_user'))
            # Check that name and surname written with correct convention, using function check_word written at the beginning of the code
            if not check_word(firstname):
                flash('Invalid First Name. First letter must be upper case and other letters lower case.', 'error')
                return redirect(url_for('add_user'))
            if not check_word(secondname):
                flash('Invalid Second Name. First letter must be upper case and other letters lower case.', 'error')
                return redirect(url_for('add_user'))
            # Password is without any restrict rules because it's a course project and the password is hashed.
            # The rule for every password is in lower case: first letter of name and first letter of surname.
            # Example: Password to Jan Nowak account is jn.

            # Check that user exists in database
            user = cursor.execute(f"SELECT id FROM user WHERE email = '{email}'").fetchone()
            if user: # If exists
                flash('Email already exists.', category='error')
                return render_template("add_user.html", subjects=subjects, classes=classes)
            try:
                if role == 'student': # If it's student, get selected class and add information to database
                    class_id = request.form.get('classes')
                    cursor.execute("INSERT INTO user(email, first_name, second_name, password, role) VALUES (?, ?, ?, ?, ?)",
                                (email, firstname, secondname, generate_password_hash(password, method='pbkdf2:sha256'), role))
                    # Get our student's ID and add information to second database
                    user_id = cursor.lastrowid
                    cursor.execute("INSERT INTO student(id, class_id) VALUES (?, ?)", (user_id, class_id))
                elif role == 'teacher': # If it's teacher, get selected subject and add information to database
                    subject_id = request.form.get('subjects')
                    cursor.execute("INSERT INTO user(email, first_name, second_name, password, role) VALUES (?, ?, ?, ?, ?)",
                                (email, firstname, secondname, generate_password_hash(password, method='pbkdf2:sha256'), role))
                    # Get our teacher's ID and add information to second database
                    user_id = cursor.lastrowid
                    cursor.execute("INSERT INTO teacher(id, subject_id) VALUES (?, ?)", (user_id, subject_id))
                else:
                    flash('Invalid role', category='error')
                    return render_template("add_user.html", subjects=subjects, classes=classes)
                conn.commit() # Save changes
                flash('User added successfully.', category='success')
                return redirect(url_for('add_user'))
            except Exception as e:
                flash(f'Error: {str(e)}', category='error')
        return render_template("add_user.html", subjects=subjects, classes=classes)
    elif current_user.role == 'student':
        return redirect(url_for('student_dashboard'))
    elif current_user.role == 'teacher':
        return redirect(url_for('teacher_dashboard'))
    elif not current_user.is_authenticated:
        return redirect(url_for('welcome'))
    
@app.route('/assign_teacher_to_class', methods=['GET', 'POST'])
@login_required
def assign_teacher_to_class():
    if current_user.role == 'admin':
        if is_session_expired():
            return redirect(url_for('logout'))
        update_last_activity() # The latest page refresh
        # Get all subjects and classes
        subjects = cursor.execute("SELECT id, name FROM subject").fetchall()
        classes = cursor.execute("SELECT id, name, profile FROM class").fetchall()
        if request.method == 'POST': # If values in page submitted
            action = request.form['action'] # 2 submit buttons with name action
            if action == 'update': # First sumbit button (choose class and subject page)
                selected_class = request.form.get('classes') # Selected class
                selected_subject = request.form.get('subjects') # Selected page
                # Check that any teacher is assigned to this class and subject together
                existing_assignment = cursor.execute(f'''SELECT id FROM teacher_class
                                                         WHERE class_id = {selected_class} AND subject_id = {selected_subject}''').fetchone()
                if existing_assignment: # If assigment exists
                    flash('Assignment for this class and subject already exists.', 'error')
                    return render_template("assign_teacher_to_class.html", classes=classes, subjects=subjects)
                else: # If not, get all teachers who can teach selected subject
                    users = cursor.execute(f'''SELECT * FROM user u
                                               LEFT JOIN teacher t ON t.id = u.id
                                               WHERE t.subject_id = {selected_subject}''').fetchall()
                    return render_template("assign_teacher_to_class_step2.html", users=users, selected_class=selected_class, selected_subject=selected_subject)
            elif action == 'save': # Second submit button (choose teacher page)
                teacher_id = request.form.get('teachers') # Selected teacher
                selected_class = request.form.get('classes') # Selected class
                selected_subject = request.form.get('subjects') # Selected subject
                # Check that teacher for 100% can teach this subject
                valid_teacher = cursor.execute(f'''SELECT u.id FROM user u
                                                   LEFT JOIN teacher t ON t.id = u.id
                                                   WHERE t.subject_id = {selected_subject}''').fetchone()
                if valid_teacher: # If he can teach, add information to database
                    cursor.execute("INSERT INTO teacher_class(teacher_id, class_id, subject_id) VALUES (?, ?, ?)", (teacher_id, selected_class, selected_subject))
                    conn.commit() # Save changes
                    flash('Assignment successfully created.', 'success')
                    return render_template("assign_teacher_to_class.html", classes=classes, subjects=subjects)
                else:
                    flash('Selected teacher does not teach the selected subject.', 'error')
            else:
                flash('Invalid action!', 'error')
                return redirect(url_for('assign_teacher_to_class'))
        return render_template("assign_teacher_to_class.html", classes=classes, subjects=subjects)
    elif current_user.role == 'student':
        return redirect(url_for('student_dashboard'))
    elif current_user.role == 'teacher':
        return redirect(url_for('teacher_dashboard'))
    elif not current_user.is_authenticated:
        return redirect(url_for('welcome'))

@app.route('/enter_grades', methods=['GET', 'POST'])
@login_required
def enter_grades():
    if current_user.role == 'teacher':
        if is_session_expired():
            return redirect(url_for('logout'))
        update_last_activity() # The latest page refresh
        # Get list of classes which logged teacher teach
        classes = cursor.execute(f'''SELECT c.id, c.name FROM teacher_class tc
                                     LEFT JOIN class c ON tc.class_id = c.id
                                     WHERE tc.teacher_id = {current_user.id}''').fetchall()
        if request.method == 'POST': # If values in page submitted
            action = request.form['gradeaction'] # 2 submit buttons with name gradeaction
            if action == 'update1': # First submit button (choose class page)
                selected_class = request.form.get('selectedClass') # Selected class
                # List of students in selected class
                students = cursor.execute(f'''SELECT u.first_name, u.second_name FROM user u
                                              LEFT JOIN student s ON s.id = u.id
                                              WHERE u.role = 'student' AND s.class_id = {selected_class}''').fetchall()
                return render_template('enter_grades_step2.html', selected_class=selected_class, students=students)
            elif action == 'update2': # Second submit button (enter grades page)
                selected_class = request.form.get('selectedClass') # Selected class
                weight = request.form.get('weight') # Selected weight
                grades = request.form.getlist('grades') # List of grades
                try:
                    weight = float(weight) # Check that value is numeric
                    if not (0 < weight <= 1): # Check that value is between 0 and 1
                        flash('Invalid weight. Must be between 0 (exclusive) and 1 (inclusive).', 'error')
                        return redirect(url_for('enter_grades'))
                except ValueError:
                    flash('Invalid weight. Must be a numeric value.', 'error')
                    return redirect(url_for('enter_grades'))
                # All possibilities to enter grade (len(grades) = number of students in class)
                for grade_value in grades:
                    if grade_value: # If grade was entered
                        try:
                            grade_value = int(grade_value) # Check that value is an integer
                            if not (1 <= grade_value <= 6): # Check that value is between 1 and 6
                                flash('Invalid grade. Must be an integer between 1 and 6 (inclusive).', 'error')
                                return redirect(url_for('enter_grades'))
                        except ValueError:
                            flash('Invalid grade. Must be an integer value.', 'error')
                            return redirect(url_for('enter_grades'))
                # Get information about logged teacher
                teacher = cursor.execute(f'''SELECT * FROM teacher
                                            WHERE id = {current_user.id}
                                            ''').fetchone()
                subject_id = teacher[1] # Teacher's subject
                teacher_id = teacher[0] # Teacher's ID
                # List of students in class
                students = cursor.execute(f'''SELECT u.id FROM user u
                                              LEFT JOIN student s ON s.id = u.id
                                              WHERE u.role = 'student' AND s.class_id = {selected_class}''').fetchall()
                # Data from table in page
                for student, grade_value in zip(students, grades):
                    if grade_value != '': # If grade was entered, add information to database
                        cursor.execute("INSERT INTO grade(value, weight, subject_id, student_id, teacher_id) VALUES (?, ?, ?, ?, ?)", 
                                       (grade_value, weight, subject_id, student[0], teacher_id))
                conn.commit() # Save all changes
                flash('Grades added!', 'success')
                return redirect(url_for('enter_grades'))
            else:
                flash('Invalid action!', 'error')
                return redirect(url_for('enter_grades'))
        return render_template('enter_grades.html', classes=classes)    
    elif current_user.role == 'student':
        return redirect(url_for('student_dashboard'))
    elif current_user.role == 'admin':
        return redirect(url_for('admin_panel'))
    elif not current_user.is_authenticated:
        return redirect(url_for('welcome'))

@app.route('/add_subject', methods=['GET', 'POST'])
@login_required
def add_subject():
    if current_user.role == 'admin':
        if is_session_expired():
            return redirect(url_for('logout'))
        update_last_activity() # The latest page refresh
        operation.create_views() # Refreshing the views every time the admin panel is opened
        # Get all subjects from views
        vsubject = cursor.execute('SELECT * FROM vw_subjects').fetchall()
        if request.method == 'POST': # If values in page submitted
            newsubject = request.form.get('newsubject') # Selected role student/teacher
            # Check that subject written with correct convention, using function check_word written at the beginning of the code
            if not check_word(newsubject):
                flash('Invalid subject name. First letter must be upper case and other letters lower case.', 'error')
                return redirect(url_for('add_subject'))
            # Check that subject exists in database
            issubject = cursor.execute(f"SELECT id FROM subject WHERE name = '{newsubject}'").fetchone()
            if issubject: # If exists
                flash('Subject already exists.', category='error')
                redirect(url_for('add_subject'))
            else: # If not, add this subject to the database and save changes
                cursor.execute(f"INSERT INTO subject(name) VALUES (?)",(newsubject,))
                conn.commit() # Save changes
                flash('Subject added successfully.', category='success')
                return redirect(url_for('add_subject'))
        return render_template("add_subject.html", vsubject=vsubject)
    
# Run the app, debug = True for automate changing app when changes in code
if __name__ == '__main__':
    app.run(debug=True)
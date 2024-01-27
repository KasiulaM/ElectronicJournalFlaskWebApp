# Electronic Journal

## Introduction

The Electronic Journal is a Flask-based web application designed to streamline administrative tasks within an educational institution. This system facilitates the management of user roles, classes, subjects, and the grading process. It offers distinct dashboards for students, teachers, and administrators.

## Installation and usage

1. Clone the repository: https://github.com/mqrcinoo/ElectronicJournalFlaskWebApp.git
2. Install all necessery packages (install packages folder and installer.ipynb file)
3. Run the main.py file and click the link printed in the terminal to the local host.
4. To login as any user write an email and password in appropirate login section. Passwords are encrypted so for every user the password is first letter of name and surname e.g. Jan Kowalski's password is jk.

## Features

### Admin

1. Admin Panel - administator may take a look at the provided data in the database.
2. Add new user - administrator can create new account for student or teacher.
3. Add new subject - administrator can create a new subject in school.
4. Assign teacher to class - administrator can give access for teacher to enter grades for dediacted class and subject.


### Teacher

1. Teacher Dashboard - Teachers can take a look at the latest grades provided and analyse the situation for each class and student they teach.
2. Enter Grades - Teacher can choose the class and then can enter grades for students in this class (it's not required to enter grades for all students in class)

### Student

1. Student Dashboard - Students can take a look at the latest grades they got, analyse they total and for each subject average. Also they can compare them with other students in class.

## Authors

Marcin Miszkiel and Katarzyna Mocio.

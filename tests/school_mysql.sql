CREATE TABLE students (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE courses (id INTEGER PRIMARY KEY, title TEXT);
CREATE TABLE enrollments (id INTEGER PRIMARY KEY, student_id INTEGER, course_id INTEGER, grade TEXT, FOREIGN KEY (student_id) REFERENCES students(id), FOREIGN KEY (course_id) REFERENCES courses(id));

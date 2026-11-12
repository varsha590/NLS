CREATE TABLE patients (id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE appointments (id INTEGER PRIMARY KEY, patient_id INTEGER, date TEXT, FOREIGN KEY (patient_id) REFERENCES patients(id));
CREATE TABLE doctors (id INTEGER PRIMARY KEY, name TEXT);

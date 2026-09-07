# Occupational Certificate: Software Developer

## mock-eisa-software_developer-paper-01

> **MOCK / PRACTICE ASSESSMENT ONLY. This paper is generated for formative self-assessment and exam-preparation purposes. It is NOT an official QCTO External Integrated Summative Assessment (EISA), is not moderated by MICT SETA, and confers no qualification status or credit.**

- **NQF Level(s):** [4, 5]
- **Duration:** 180 minutes
- **Total Marks:** 100

## Instructions to Candidates

1. This is a MOCK / PRACTICE assessment for formative preparation. It is NOT an official QCTO External Integrated Summative Assessment (EISA) and carries no official qualification status.
1. Answer ALL questions in ALL sections.
1. Read each scenario carefully before answering; several questions integrate more than one competency area.
1. Write code answers in plain text/pseudocode unless a specific language is requested; assume standard syntax for the language named in the question.
1. Show your reasoning for calculation and design questions - partial credit is available and requires visible working.
1. Manage your time: indicative mark values show the expected effort per question.
1. No electronic devices other than those explicitly permitted by your facilitator may be used.

## Section A: Programming Fundamentals and Logical Reasoning (15 marks)

### Question A1 (15 marks)

*Scenario:* You are a junior developer at Thusong Logistics, a fleet-tracking startup. Before extending the driver dashboard, your lead asks you to work through some numeric and logic checks on paper so the team can confirm your understanding before you touch the codebase.

Answer each part below, showing your working.

**(1)** A vehicle's onboard unit reports an odometer delta as the binary value 10110. Working from the rightmost digit, determine its decimal equivalent and show the contribution of each bit position. *[3 marks]*

**(2)** A teammate hard-codes a trip-cost estimate as `distance = 23 % 4 * 2 - 5 + 1`. Work out the value `distance` ends up with. For each step, state which single operation you resolved and why it had to happen at that point relative to the others. *[4 marks]*

**(3)** A colleague asks you to review their pull request without running it. Step through the following block one line at a time and record every value it prints, in the order it prints them:
```
speed = 50
checks = 0
while checks < 4:
    if speed > 60:
        print("over limit")
    speed = speed + 5
    checks = checks + 1
``` *[4 marks]*

**(4)** In Python, a colleague wrote this line to log a trip summary:
`log = "Trip length: " + 12.3 + " km"`
Running it raises `TypeError: can only concatenate str (not "float") to str`. Explain precisely why Python raises this error here, and rewrite the line so it runs successfully and produces the string `"Trip length: 12.3 km"`. *[4 marks]*

## Section B: Front-End Web Development (HTML5, CSS, JavaScript, OOP) (30 marks)

### Question B1 (30 marks)

*Scenario:* A small independent bookshop, Paper Trail Books, wants a simple 'Reading Club Sign-Up' feature added to their existing website so visitors can register interest without an account. You have been asked to build the front end for this feature.

Complete the following front-end development tasks for the Reading Club Sign-Up feature.

**(1)** Write a semantic HTML5 form that captures: full name (required), email address (required, must be a valid email format), and favourite genres as checkboxes for 'Fiction', 'Non-Fiction' and 'Poetry' - the form's requirement is that at least one genre MUST be selected before the form can be submitted. Use appropriate input types and attributes so the browser natively validates the name and email fields without any JavaScript. Then, in 1-2 sentences, state whether HTML5's `required` attribute can, by itself, enforce this at-least-one-checkbox requirement, and explain what you would need to add to actually enforce it. *[6 marks]*

**(2)** Using CSS Flexbox, style the form so that on small screens each label appears above its input (stacked, single column), and on screens 768px and wider the labels appear beside their inputs in a single row per field. Include the media query and explain in one sentence why Flexbox is a suitable choice here. *[6 marks]*

**(3)** Write JavaScript that intercepts the form's submit event, prevents the default page reload, checks that the name field is not empty and the email field contains an '@' and at least one '.' after it, and - if invalid - displays an inline error message next to the field without using `alert()`. If valid, log the form data to the console. *[8 marks]*

**(4)** You are given this object literal used to track a reading-club member:
```javascript
let member = { name: "Sipho", booksRead: 2 };
```
Refactor this into an ES6 class named `Member` with a constructor, a private or underscore-convention field for `booksRead`, a getter for `booksRead`, and a setter that rejects negative values. Name the specific OOP principle your getter/setter design demonstrates and explain, in 1-2 sentences, why it matters here. *[10 marks]*

## Section C: Systems Modelling with UML (15 marks)

### Question C1 (15 marks)

*Scenario:* A small clinic wants to introduce a simple appointment booking feature: a Patient may book an Appointment with a Doctor; if the requested slot is full, the request joins a waitlist and the Patient is notified when a slot opens up.

Model the following aspects of the booking feature using UML.

**(1)** Describe a class diagram for this feature. For each of `Patient`, `Doctor`, and `Appointment`, list at least 3 relevant attributes and 2 relevant methods, and describe the association(s) between the classes including multiplicity (e.g. one-to-many). You may describe this in structured text/UML notation; a hand-drawn diagram is not required. *[8 marks]*

**(2)** Describe, as a sequence of numbered messages between objects (as you would read off a sequence diagram), the flow when a Patient requests an Appointment slot that is full: include at least the Patient, a BookingService, the Doctor's schedule, and a notification step once a slot opens up. *[7 marks]*

## Section D: Data, Databases and Querying (20 marks)

### Question D1 (20 marks)

*Scenario:* Thusong Logistics (from Section A) needs a small relational database to track vehicles and the maintenance depots that service them, so staff can quickly see which vehicles are due for a service.

Complete the following database tasks.

**(1)** Write CREATE TABLE statements for `Depots` (depot_id, name, contact_email) and `Vehicles` (vehicle_id, registration, km_since_service, service_interval_km, depot_id). Choose appropriate data types and define the primary key on each table and the foreign key relationship between them. *[6 marks]*

**(2)** Write a single SQL query that lists the vehicle registration, km_since_service, and depot contact email for every vehicle where km_since_service is greater than its service_interval_km, ordered by km_since_service descending. *[6 marks]*

**(3)** Write an SQL statement that resets km_since_service to 0 for every vehicle serviced by depot_id = 2. Then, in 1-2 sentences, explain why omitting the WHERE clause on an UPDATE statement like this is dangerous. *[4 marks]*

**(4)** Two dispatchers open the same vehicle record at the same time and both save changes. Describe one practical technique a database or application can use to prevent one person's update from silently overwriting the other's. *[4 marks]*

## Section E: SDLC, Algorithms and Secure Coding (15 marks)

### Question E1 (15 marks)

*Scenario:* Your team is midway through building a new appointment-reminder feature. The team lead shares a short project update and asks you to reflect on process and security.

Answer the following questions about SDLC, algorithms, and secure coding.

**(1)** The update reads: 'We've mapped out every screen and written down exactly what data each one needs before anyone starts coding.' Identify which SDLC phase this describes and justify your answer in 1-2 sentences. *[4 marks]*

**(2)** Write pseudocode for an algorithm that finds any duplicate phone number in a list of patient phone numbers and returns the first duplicate found (or a clear 'none found' result). State the time complexity of your algorithm using Big-O notation and justify it in one sentence. *[6 marks]*

**(3)** A colleague wrote this code to look up a patient by surname:
```python
query = "SELECT * FROM patients WHERE surname = '" + user_input + "'"
```
Identify the security vulnerability in this code and rewrite it using a safe approach (e.g. parameterised query), explaining briefly why your version is safe. *[5 marks]*

## Section F: Workplace Integration and Professional Practice (5 marks)

### Question F1 (5 marks)

*Scenario:* A teammate says: 'We're behind schedule - let's skip logging what changed in this release so we can ship faster. No one reads those notes anyway.'

Identify one workplace governance or professional-practice principle relevant to this situation, and explain in a short paragraph what you should do, and why.

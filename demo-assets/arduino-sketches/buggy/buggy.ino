/*
 * Elegoo V4 Smart Robot Car — Obstacle Avoidance (BUGGY)
 * BUG: KP=50.0 causes violent oscillation, KD=0.0 provides no damping.
 *
 * Hardware:
 *   TB6612FNG motor driver: PWMA=5, AIN1=7, AIN2=4, PWMB=6, BIN1=8, BIN2=9, STBY=3
 *   HC-SR04 ultrasonic: TRIG=13, ECHO=12
 *   SG90 servo: pin 10
 *   4 DC motors: left pair on channel A, right pair on channel B
 *   Serial at 9600 baud
 */

#include <Servo.h>

// Motor driver pins (TB6612FNG)
#define PWMA 5
#define AIN1 7
#define AIN2 4
#define PWMB 6
#define BIN1 8
#define BIN2 9
#define STBY 3

// Ultrasonic sensor pins (HC-SR04)
#define TRIG 13
#define ECHO 12

// Servo pin (SG90)
#define SERVO_PIN 10

Servo headServo;

// PID parameters — BUGGY VALUES
float KP = 50.0;  // BUG: should be ~2.0
float KD = 0.0;   // BUG: should be ~0.5

// State
bool pidRunning = false;
bool manualOverride = false;
unsigned long manualExpiry = 0;
float pidError = 0.0;
float pidLastError = 0.0;
int leftPWM = 0;
int rightPWM = 0;
int baseSpeed = 120;
unsigned long lastTelemetry = 0;

// ── Motor control ──

void motorA(int speed) {
  if (speed > 0) {
    digitalWrite(AIN1, HIGH);
    digitalWrite(AIN2, LOW);
    analogWrite(PWMA, constrain(speed, 0, 255));
  } else if (speed < 0) {
    digitalWrite(AIN1, LOW);
    digitalWrite(AIN2, HIGH);
    analogWrite(PWMA, constrain(-speed, 0, 255));
  } else {
    digitalWrite(AIN1, LOW);
    digitalWrite(AIN2, LOW);
    analogWrite(PWMA, 0);
  }
}

void motorB(int speed) {
  if (speed > 0) {
    digitalWrite(BIN1, HIGH);
    digitalWrite(BIN2, LOW);
    analogWrite(PWMB, constrain(speed, 0, 255));
  } else if (speed < 0) {
    digitalWrite(BIN1, LOW);
    digitalWrite(BIN2, HIGH);
    analogWrite(PWMB, constrain(-speed, 0, 255));
  } else {
    digitalWrite(BIN1, LOW);
    digitalWrite(BIN2, LOW);
    analogWrite(PWMB, 0);
  }
}

void driveMotors(int left, int right) {
  motorA(left);
  motorB(right);
}

void stopMotors() {
  motorA(0);
  motorB(0);
}

// ── Ultrasonic sensor ──

long readDistance() {
  digitalWrite(TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG, LOW);
  long duration = pulseIn(ECHO, HIGH, 30000);
  if (duration == 0) return -1;
  return duration * 0.034 / 2;
}

// ── Serial command handler ──

void handleCommands() {
  if (!Serial.available()) return;
  String cmd = Serial.readStringUntil('\n');
  cmd.trim();

  if (cmd == "START") {
    pidRunning = true;
    pidError = 0;
    pidLastError = 0;
  }
  else if (cmd == "STOP") {
    pidRunning = false;
    stopMotors();
    leftPWM = 0;
    rightPWM = 0;
    pidError = 0;
    pidLastError = 0;
  }
  else if (cmd == "SWEEP") {
    headServo.write(0);
    delay(300);
    headServo.write(180);
    delay(300);
    headServo.write(90);
  }
  else if (cmd == "FORWARD") {
    manualOverride = true;
    manualExpiry = millis() + 500;
    leftPWM = 153; rightPWM = 153;
    driveMotors(leftPWM, rightPWM);
  }
  else if (cmd == "REVERSE") {
    manualOverride = true;
    manualExpiry = millis() + 500;
    leftPWM = -153; rightPWM = -153;
    driveMotors(leftPWM, rightPWM);
  }
  else if (cmd == "LEFT") {
    manualOverride = true;
    manualExpiry = millis() + 500;
    leftPWM = -128; rightPWM = 128;
    driveMotors(leftPWM, rightPWM);
  }
  else if (cmd == "RIGHT") {
    manualOverride = true;
    manualExpiry = millis() + 500;
    leftPWM = 128; rightPWM = -128;
    driveMotors(leftPWM, rightPWM);
  }
}

// ── Setup ──

void setup() {
  Serial.begin(9600);

  pinMode(PWMA, OUTPUT);
  pinMode(AIN1, OUTPUT);
  pinMode(AIN2, OUTPUT);
  pinMode(PWMB, OUTPUT);
  pinMode(BIN1, OUTPUT);
  pinMode(BIN2, OUTPUT);
  pinMode(STBY, OUTPUT);
  pinMode(TRIG, OUTPUT);
  pinMode(ECHO, INPUT);

  digitalWrite(STBY, HIGH);
  stopMotors();

  headServo.attach(SERVO_PIN);
  headServo.write(90);
}

// ── Main loop ──

void loop() {
  handleCommands();

  // Auto-expire manual override after timeout
  if (manualOverride && millis() > manualExpiry) {
    manualOverride = false;
    stopMotors();
    leftPWM = 0;
    rightPWM = 0;
  }

  long dist = readDistance();

  if (pidRunning && !manualOverride && dist > 0 && dist < 100) {
    pidError = dist - 25.0;
    float derivative = pidError - pidLastError;
    float output = KP * pidError + KD * derivative;
    pidLastError = pidError;

    leftPWM = constrain(baseSpeed + (int)output, -255, 255);
    rightPWM = constrain(baseSpeed - (int)output, -255, 255);
    driveMotors(leftPWM, rightPWM);
  }
  else if (pidRunning && !manualOverride) {
    leftPWM = baseSpeed;
    rightPWM = baseSpeed;
    driveMotors(baseSpeed, baseSpeed);
  }
  else if (!pidRunning && !manualOverride) {
    leftPWM = 0;
    rightPWM = 0;
  }

  // Telemetry at 5Hz — compact CSV to avoid TX buffer blocking
  if (millis() - lastTelemetry >= 200) {
    lastTelemetry = millis();

    Serial.print(F("distance_cm="));  Serial.print(dist);
    Serial.print(F(",left_motor="));  Serial.print(leftPWM / 255.0, 3);
    Serial.print(F(",right_motor=")); Serial.print(rightPWM / 255.0, 3);
    Serial.print(F(",pid_error="));   Serial.print(pidError, 2);
    Serial.print(F(",kp_value="));    Serial.print(KP, 1);
    Serial.print(F(",kd_value="));    Serial.print(KD, 1);
    Serial.print(F(",running="));     Serial.print(pidRunning ? 1 : 0);
    Serial.print(F(",bug_active=1"));
    Serial.println();
  }

  delay(10);
}

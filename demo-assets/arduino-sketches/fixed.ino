#include <Servo.h>
#define PWMA 5
#define AIN1 7
#define PWMB 6
#define BIN1 8
#define STBY 3
#define TRIG 13
#define ECHO 12
#define SERVO_PIN 10
Servo headServo;
bool robotRunning = false;
float KP = 2.0;
float KD = 0.5;
float pidError = 0, pidLastError = 0;
int leftPWM = 0, rightPWM = 0;
unsigned long lastSend = 0;
void setup() {
  Serial.begin(9600);
  pinMode(PWMA, OUTPUT); pinMode(AIN1, OUTPUT);
  pinMode(PWMB, OUTPUT); pinMode(BIN1, OUTPUT);
  pinMode(STBY, OUTPUT);
  pinMode(TRIG, OUTPUT); pinMode(ECHO, INPUT);
  headServo.attach(SERVO_PIN); headServo.write(90);
  digitalWrite(STBY, HIGH);
  analogWrite(PWMA, 0); analogWrite(PWMB, 0);
}
long readDistance() {
  digitalWrite(TRIG, LOW); delayMicroseconds(2);
  digitalWrite(TRIG, HIGH); delayMicroseconds(10);
  digitalWrite(TRIG, LOW);
  long d = pulseIn(ECHO, HIGH, 30000);
  return d == 0 ? -1 : d * 0.034 / 2;
}
void driveMotors(int left, int right) {
  if (left >= 0) { digitalWrite(AIN1, HIGH); analogWrite(PWMA, constrain(left, 0, 255)); }
  else { digitalWrite(AIN1, LOW); analogWrite(PWMA, constrain(-left, 0, 255)); }
  if (right >= 0) { digitalWrite(BIN1, HIGH); analogWrite(PWMB, constrain(right, 0, 255)); }
  else { digitalWrite(BIN1, LOW); analogWrite(PWMB, constrain(-right, 0, 255)); }
}
void handleCommands() {
  if (!Serial.available()) return;
  String cmd = Serial.readStringUntil('\n'); cmd.trim();
  if (cmd == "START") robotRunning = true;
  else if (cmd == "STOP") { robotRunning = false; driveMotors(0,0); leftPWM=0; rightPWM=0; pidError=0; pidLastError=0; }
  else if (cmd == "SWEEP") { headServo.write(0); delay(300); headServo.write(180); delay(300); headServo.write(90); }
}
void loop() {
  handleCommands();
  long dist = readDistance();
  if (robotRunning && dist > 0 && dist < 100) {
    pidError = dist - 25.0;
    float output = KP * pidError + KD * (pidError - pidLastError);
    pidLastError = pidError;
    leftPWM = constrain(120 + (int)output, -255, 255);
    rightPWM = constrain(120 - (int)output, -255, 255);
    driveMotors(leftPWM, rightPWM);
  } else if (robotRunning) {
    leftPWM = 120; rightPWM = 120; driveMotors(120, 120);
  } else {
    leftPWM = 0; rightPWM = 0; driveMotors(0, 0);
  }
  if (millis() - lastSend >= 100) {
    lastSend = millis();
    Serial.print(F("{\"signals\":["));
    Serial.print(F("{\"name\":\"distance_cm\",\"value\":")); Serial.print(dist);
    Serial.print(F(",\"unit\":\"cm\"},"));
    Serial.print(F("{\"name\":\"left_motor\",\"value\":")); Serial.print(leftPWM/255.0, 3);
    Serial.print(F(",\"unit\":\"norm\"},"));
    Serial.print(F("{\"name\":\"right_motor\",\"value\":")); Serial.print(rightPWM/255.0, 3);
    Serial.print(F(",\"unit\":\"norm\"},"));
    Serial.print(F("{\"name\":\"pid_error\",\"value\":")); Serial.print(pidError, 2);
    Serial.print(F(",\"unit\":\"\"},"));
    Serial.print(F("{\"name\":\"kp_value\",\"value\":")); Serial.print(KP, 1);
    Serial.print(F(",\"unit\":\"\"},"));
    Serial.print(F("{\"name\":\"kd_value\",\"value\":")); Serial.print(KD, 1);
    Serial.print(F(",\"unit\":\"\"},"));
    Serial.print(F("{\"name\":\"running\",\"value\":")); Serial.print(robotRunning ? 1 : 0);
    Serial.print(F(",\"unit\":\"\"},"));
    Serial.print(F("{\"name\":\"bug_active\",\"value\":0,\"unit\":\"\"}"));
    Serial.println(F("]}"));
  }
  delay(10);
}

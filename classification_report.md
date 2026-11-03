# Database Column Classification Report

Deny-first privacy classification summary across all catalog columns.
Values, row data, and credentials are never included in this report.

## Summary Counts

| Class | Column Count | Description |
|---|---|---|
| **BLOCKED** | 80 | Completely excluded from DDL, embeddings, retriever, and logs |
| **MASKED** | 0 | Retained in DDL for queries; output values masked |
| **VALUE_LOW** | 318 | Fully indexed for value resolution (distinct count <= threshold) |
| **VALUE_HIGH** | 1 | Resolved dynamically at query time; not sent to LLM |
| **SKIP** | 477 | Keys, non-text, free text, embeddings, hashes (retained in DDL for joins) |
| **Total** | 876 | Total columns classified |

## Catalog Size

Tables included: **72**
Columns included: **876**

## POSSIBLE DUPLICATE TABLES

Structure similarity threshold: 90%. Detection uses column-name/type structure only; groups are advisory and no tables are excluded automatically.

| Group | Tables | Minimum matched similarity |
|---|---|---:|
| 1 | `access_permission`, `access_permission_bk(01apr2024)` | 90.0% |
| 2 | `admin`, `admin_bk(28mar2024)` | 92.9% |
| 3 | `assign_access_permission`, `assign_access_permission_bk(28mar2024)` | 100.0% |
| 4 | `email_templates`, `email_templates_2026(bk)`, `email_templates_bk2025`, `email_templates_prev` | 100.0% |
| 5 | `santa_availability`, `santa_non_availability` | 100.0% |

## REVIEW

Low-cardinality columns with non-credential sensitive-name matches and no detected PII-shaped values. They remain VALUE_LOW for manual review.

| Table | Column | Matched pattern(s) | Option / distinct count |
|---|---|---|---:|
| `assign_talent` | `eEmailStatus` | email | 0 |
| `assign_talent` | `eTalentEmailStatus` | email | 0 |
| `auto_register_santa_schedule` | `eEmailStatus` | email | 3 |
| `client` | `eEmailListed` | email | 2 |
| `client` | `eMobileListed` | mobile | 2 |
| `client` | `vPhoneOther` | phone | 1 |
| `email_logs` | `vEmailTo` | email | 0 |
| `email_templates` | `vEmailSubject` | email | 56 |
| `email_templates_2026(bk)` | `vEmailSubject` | email | 55 |
| `email_templates_bk2025` | `vEmailSubject` | email | 53 |
| `email_templates_prev` | `vEmailSubject` | email | 51 |
| `event_assign_schedule` | `eEmailStatus` | email | 3 |
| `event_location` | `eSessionType` | session | 2 |
| `event_location` | `vContactPerson` | contact | 45 |
| `event_notifications` | `eEmail` | email | 2 |
| `invoice` | `eEmailStatus` | email | 0 |
| `santa_details` | `vDayContactNumber` | contact | 1 |
| `santa_details` | `vEveningContactNumber` | contact | 1 |
| `schedule_events` | `emailStatus` | email | 3 |
| `talent_person_details` | `tAddress` | address | 12 |
| `users` | `eMobileListed` | mobile | 2 |
| `users` | `eEmailListed` | email | 2 |
| `users` | `vSeasonAddress` | address | 0 |

## FLAG-LIKE VALUE COLUMNS

VALUE_LOW columns whose declared options are all digits or a recognized boolean-like pair. Meaning is intentionally not inferred.

| Table | Column | Option count | Options |
|---|---|---:|---|
| `admin` | `eVerified` | 2 | 0, 1 |
| `admin` | `eDeleteEventStatus` | 2 | Enabled, Disabled |
| `admin_bk(28mar2024)` | `eVerified` | 2 | 0, 1 |
| `affiliate_codes` | `eStatus` | 2 | enabled, disabled |
| `appointment` | `eCanReschedule` | 2 | 0, 1 |
| `appointment` | `isReminded` | 2 | 0, 1 |
| `appointment` | `isSantaReminded` | 2 | 0, 1 |
| `appointment` | `eRescheduleByAdmin` | 2 | 1, 0 |
| `appointment` | `eLinkMailSend` | 2 | 0, 1 |
| `assign_talent` | `eTalentPaid` | 2 | yes, no |
| `calendar_auth_detail` | `eCalStatus` | 2 | 0, 1 |
| `client` | `eEmailListed` | 2 | 0, 1 |
| `client` | `eMobileListed` | 2 | 0, 1 |
| `client` | `ePhnHomeListed` | 2 | 0, 1 |
| `client` | `ePhnOffcListed` | 2 | 0, 1 |
| `client` | `ePhnOtherListed` | 2 | 0, 1 |
| `client` | `eWebListed` | 2 | 0, 1 |
| `email_logs` | `eDeleteStatus` | 2 | 0, 1 |
| `email_templates` | `eStatus` | 2 | 0, 1 |
| `email_templates_2026(bk)` | `eStatus` | 2 | 0, 1 |
| `email_templates_bk2025` | `eStatus` | 2 | 0, 1 |
| `email_templates_prev` | `eStatus` | 2 | 0, 1 |
| `event_location` | `eSameLocation` | 2 | 0, 1 |
| `event_notifications` | `eSMS` | 2 | 1, 0 |
| `event_notifications` | `eEmail` | 2 | 1, 0 |
| `event_notifications` | `eSanta` | 2 | 1, 0 |
| `event_notifications` | `eUser` | 2 | 1, 0 |
| `event_notifications` | `eAdmin` | 2 | 1, 0 |
| `global_settings` | `eIsVisible` | 2 | 0, 1 |
| `invoice` | `eNoSalesTax` | 2 | off, on |
| `invoice_due_date` | `eHideBox` | 2 | 0, 1 |
| `invoice_payment` | `eRefunded` | 2 | Yes, No |
| `invoice_payment` | `is_fully_refunded` | 2 | yes, no |
| `promo_codes` | `eStatus` | 2 | enabled, disabled |
| `retail_affiliates` | `eStatus` | 2 | Enabled, Disabled |
| `santa_details` | `eMarkAsPCR` | 2 | 1, 0 |
| `santa_screening_data` | `eSantaDress` | 2 | yes, no |
| `sms_templates` | `eStatus` | 2 | 1, 0 |
| `talent_person_details` | `eStatus` | 2 | Disabled, Enabled |
| `users` | `eVerified` | 2 | 0, 1 |
| `users` | `eStatus` | 2 | Disabled, Enabled |
| `users` | `eMobileListed` | 2 | 0, 1 |
| `users` | `eEmailListed` | 2 | 0, 1 |
| `users` | `ePhnHomeListed` | 2 | 0, 1 |
| `users` | `ePhnOffcListed` | 2 | 0, 1 |
| `users` | `ePhnOtherListed` | 2 | 0, 1 |
| `users` | `eWebListed` | 2 | 0, 1 |
| `users` | `eIsGoogleCalendar` | 2 | yes, no |

## Columns With Stats Unavailable

0 columns had stats unavailable.

## Sensitive-Value Shape Checks Unavailable

0 sensitive-value shape checks were unavailable.

## Ambiguous / Weak Token Matches (Review Recommended)

Columns blocked by a short or generic token where manual review may be helpful:

| Table | Column | Matched Token(s) | Reason |
|---|---|---|---|
| `admin` | `vContactNumber` | `contact` | blocked by name pattern: 'contact' |
| `admin` | `vResetToken` | `token` | blocked by name pattern: 'token' |
| `admin` | `dTokenTime` | `token` | blocked by name pattern: 'token' |
| `admin_bk(28mar2024)` | `vContactNumber` | `contact` | blocked by name pattern: 'contact' |
| `admin_bk(28mar2024)` | `vResetToken` | `token` | blocked by name pattern: 'token' |
| `admin_bk(28mar2024)` | `dTokenTime` | `token` | blocked by name pattern: 'token' |
| `appointment` | `vContactNumber` | `contact` | blocked by name pattern: 'contact' |
| `appointment` | `vSessionId` | `session` | blocked by name pattern: 'session' |
| `appointment` | `vAppointmentToken` | `token` | blocked by name pattern: 'token' |
| `calendar_auth_detail` | `vAccessToken` | `token` | blocked by name pattern: 'token' |
| `calendar_auth_detail` | `vRefreshToken` | `token` | blocked by name pattern: 'token' |
| `calendar_auth_detail` | `vNextSyncToken` | `token` | blocked by name pattern: 'token' |
| `children` | `dChildBirthDate` | `birth` | blocked by name pattern: 'birth' |
| `retail_affiliates` | `vContactNumber` | `contact` | blocked by name pattern: 'contact' |
| `santas_finder_details` | `ContactId` | `contact` | blocked by name pattern: 'contact' |
| `users` | `vContactNumber` | `contact` | blocked by name pattern: 'contact' |
| `users` | `dDob` | `dob` | blocked by name pattern: 'dob' |
| `users` | `vAccessToken` | `token` | blocked by name pattern: 'token' |
| `users` | `vActivationToken` | `token` | blocked by name pattern: 'token' |
| `users` | `vResetToken` | `token` | blocked by name pattern: 'token' |
| `users` | `dTokenTime` | `token` | blocked by name pattern: 'token' |

## Detailed Column Classifications

| Table | Column | SQL Type | Class | Distinct Count | Reason |
|---|---|---|---|---|---|
| `admin` | `dTokenTime` | `DATETIME` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `admin` | `iPhoneCode` | `INTEGER` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `admin` | `vContactNumber` | `VARCHAR(20) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 7 | blocked by name pattern: 'contact' |
| `admin` | `vEmail` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 8 | blocked by name pattern: 'email' |
| `admin` | `vPassword` | `VARCHAR(200) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'password' |
| `admin` | `vResetToken` | `VARCHAR(10) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `admin_bk(28mar2024)` | `dTokenTime` | `DATETIME` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `admin_bk(28mar2024)` | `iPhoneCode` | `INTEGER` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `admin_bk(28mar2024)` | `vContactNumber` | `VARCHAR(20) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 6 | blocked by name pattern: 'contact' |
| `admin_bk(28mar2024)` | `vEmail` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 9 | blocked by name pattern: 'email' |
| `admin_bk(28mar2024)` | `vPassword` | `VARCHAR(200) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'password' |
| `admin_bk(28mar2024)` | `vResetToken` | `VARCHAR(10) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `appointment` | `iPhoneCode` | `INTEGER` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `appointment` | `vAppointmentToken` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `appointment` | `vContactNumber` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 61 | blocked by name pattern: 'contact' |
| `appointment` | `vEmail` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 106 | blocked by name pattern: 'email' |
| `appointment` | `vSessionId` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'session' |
| `appointment_parties` | `iPhoneCode` | `INTEGER` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `appointment_parties` | `vEmail` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 28 | blocked by name pattern: 'email' |
| `appointment_parties` | `vPhoneNo` | `VARCHAR(20) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 24 | blocked by name pattern: 'phone' |
| `assign_talent` | `tAddress` | `TEXT COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 77 | blocked by name pattern: 'address' |
| `auto_register_santa_schedule` | `dEmailSentDate` | `DATETIME` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `auto_register_santa_schedule` | `vEmailFailMessage` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `calendar_auth_detail` | `vAccessToken` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `calendar_auth_detail` | `vNextSyncToken` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `calendar_auth_detail` | `vRefreshToken` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `children` | `dChildBirthDate` | `DATE` | **BLOCKED** | - | blocked by name pattern: 'birth' |
| `client` | `iMobileCode` | `INTEGER` | **BLOCKED** | - | blocked by name pattern: 'mobile' |
| `client` | `tAddress` | `TEXT COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 33 | blocked by name pattern: 'address' |
| `client` | `vEmail` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 47 | blocked by name pattern: 'email' |
| `client` | `vMobile` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 58 | blocked by name pattern: 'mobile' |
| `client` | `vMobileExt` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 5 | blocked by name pattern: 'mobile' |
| `client` | `vPhoneHome` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 9 | blocked by name pattern: 'phone' |
| `client` | `vPhoneOffice` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 5 | blocked by name pattern: 'phone' |
| `countries` | `phoneCode` | `INTEGER` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `email_logs` | `tEmailBody` | `TEXT COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `email_logs` | `vEmailCc` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 29 | blocked by name pattern: 'email' |
| `email_logs` | `vEmailFrom` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 5 | blocked by name pattern: 'email' |
| `event_assign_schedule` | `dEmailSentDate` | `DATETIME` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `event_assign_schedule` | `dLastEmailAttempt` | `DATETIME` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `event_assign_schedule` | `iEmailRetryCount` | `TINYINT` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `event_assign_schedule` | `vEmailFailMessage` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `event_details` | `locationAddress` | `TEXT COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 19 | blocked by name pattern: 'address' |
| `event_location` | `tAddress` | `TEXT COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 48 | blocked by name pattern: 'address' |
| `event_location` | `vAltEmail` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 18 | blocked by name pattern: 'email' |
| `event_location` | `vAltPhoneNumber` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 86 | blocked by name pattern: 'phone' |
| `event_location` | `vEmail` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 39 | blocked by name pattern: 'email' |
| `event_location` | `vPhoneNumber` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 117 | blocked by name pattern: 'phone' |
| `invoice` | `dOtpCreatedAt` | `DATETIME` | **BLOCKED** | - | blocked by name pattern: 'otp' |
| `invoice` | `dReminderEmailSentDate` | `DATE` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `invoice` | `vOtp` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'otp' |
| `retail_affiliates` | `iPhoneCode` | `INTEGER` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `retail_affiliates` | `vContactNumber` | `VARCHAR(20) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 5 | blocked by name pattern: 'contact' |
| `retail_affiliates` | `vEmail` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 10 | blocked by name pattern: 'email' |
| `santa_emergency_contact` | `vSantaAddress` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 5 | blocked by name pattern: 'address' |
| `santa_emergency_contact` | `vSantaEmail` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 7 | blocked by name pattern: 'email' |
| `santa_emergency_contact` | `vSantaPhone` | `INTEGER` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `santas_finder_details` | `ContactId` | `INTEGER` | **BLOCKED** | - | blocked by name pattern: 'contact' |
| `santas_finder_details` | `Email` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 3 | blocked by name pattern: 'email' |
| `santas_finder_details` | `PhoneNumber` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 501 | blocked by name pattern: 'phone' |
| `schedule_events` | `emailFailMessage` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `schedule_events` | `emailSentDate` | `DATETIME` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `schedule_events` | `santaEmail` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 33 | blocked by name pattern: 'email' |
| `schedule_events` | `santaPhoneNumber` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 30 | blocked by name pattern: 'phone' |
| `talent_person_details` | `iMobileCode` | `INTEGER` | **BLOCKED** | - | blocked by name pattern: 'mobile' |
| `talent_person_details` | `vEmail` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 35 | blocked by name pattern: 'email' |
| `talent_person_details` | `vMobile` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 31 | blocked by name pattern: 'mobile' |
| `users` | `dDob` | `DATETIME` | **BLOCKED** | - | blocked by name pattern: 'dob' |
| `users` | `dTokenTime` | `DATETIME` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `users` | `iPhoneCode` | `INTEGER` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `users` | `tAddress` | `MEDIUMTEXT` | **BLOCKED** | 27 | blocked by name pattern: 'address' |
| `users` | `vAccessToken` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `users` | `vActivationToken` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `users` | `vContactNumber` | `VARCHAR(15) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 114 | blocked by name pattern: 'contact' |
| `users` | `vEmail` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 163 | blocked by name pattern: 'email' |
| `users` | `vPassword` | `VARCHAR(200) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'password' |
| `users` | `vPhoneHome` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 3 | blocked by name pattern: 'phone' |
| `users` | `vPhoneOffice` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 3 | blocked by name pattern: 'phone' |
| `users` | `vPhoneOther` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | 2 | blocked by name pattern: 'phone' |
| `users` | `vResetToken` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `access_permission` | `eViewType` | `ENUM` (options: parent, child) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `access_permission` | `tIconName` | `TEXT COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 18 | text column with distinct count 18 <= threshold 500 |
| `access_permission` | `vModuleName` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 55 | text column with distinct count 55 <= threshold 500 |
| `access_permission` | `vUrl` | `VARCHAR(120) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 47 | text column with distinct count 47 <= threshold 500 |
| `access_permission_bk(01apr2024)` | `tIconName` | `TEXT COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 18 | text column with distinct count 18 <= threshold 500 |
| `access_permission_bk(01apr2024)` | `vModuleName` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 53 | text column with distinct count 53 <= threshold 500 |
| `access_permission_bk(01apr2024)` | `vUrl` | `VARCHAR(120) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 46 | text column with distinct count 46 <= threshold 500 |
| `admin` | `eDeleteEventStatus` | `ENUM` (options: Enabled, Disabled) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `admin` | `eUserType` | `ENUM` (options: Admin, User, Subadmin) | **VALUE_LOW** | 3 | declared option count 3 <= threshold 500 |
| `admin` | `eVerified` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `admin` | `vFirstName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 6 | text column with distinct count 6 <= threshold 500 |
| `admin` | `vLastName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 6 | text column with distinct count 6 <= threshold 500 |
| `admin` | `vProfilePic` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | text column with distinct count 1 <= threshold 500 |
| `admin_bk(28mar2024)` | `eUserType` | `ENUM` (options: Admin, User, Subadmin) | **VALUE_LOW** | 3 | declared option count 3 <= threshold 500 |
| `admin_bk(28mar2024)` | `eVerified` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `admin_bk(28mar2024)` | `vFirstName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 8 | text column with distinct count 8 <= threshold 500 |
| `admin_bk(28mar2024)` | `vLastName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 6 | text column with distinct count 6 <= threshold 500 |
| `admin_bk(28mar2024)` | `vProfilePic` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | text column with distinct count 1 <= threshold 500 |
| `affiliate_codes` | `eAffiliateType` | `ENUM` (options: general, santa) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `affiliate_codes` | `eCommissionType` | `ENUM` (options: fixed, percent) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `affiliate_codes` | `eDiscountType` | `ENUM` (options: fixed, percent) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `affiliate_codes` | `eStatus` | `ENUM` (options: enabled, disabled) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `affiliate_codes` | `vAffiliateCode` | `VARCHAR(20) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 13 | text column with distinct count 13 <= threshold 500 |
| `affiliate_codes` | `vAffiliateLink` | `VARCHAR(500) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 13 | text column with distinct count 13 <= threshold 500 |
| `affiliate_codes` | `vAffiliateName` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 13 | text column with distinct count 13 <= threshold 500 |
| `appointment` | `eAppointmentStatus` | `ENUM` (options: Pending, Missed, Confirmed, Complete, Cancel) | **VALUE_LOW** | 5 | declared option count 5 <= threshold 500 |
| `appointment` | `eAppointmentType` | `ENUM` (options: live_video_call, personalized_call) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `appointment` | `eCanReschedule` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `appointment` | `eChildReminderStatus` | `ENUM` (options: Sent, Error) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `appointment` | `eFileStatus` | `ENUM` (options: recorded, encoded, sent, encoding) | **VALUE_LOW** | 4 | declared option count 4 <= threshold 500 |
| `appointment` | `eLinkMailSend` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `appointment` | `eRescheduleByAdmin` | `ENUM` (options: 1, 0) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `appointment` | `iAppointmentNum` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 142 | text column with distinct count 142 <= threshold 500 |
| `appointment` | `isDefferentExitVideo` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 0 | text column with distinct count 0 <= threshold 500 |
| `appointment` | `isReminded` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `appointment` | `isSantaReminded` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `appointment` | `vEncodedFIle` | `VARCHAR(500) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 0 | text column with distinct count 0 <= threshold 500 |
| `appointment` | `vFirstName` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 63 | text column with distinct count 63 <= threshold 500 |
| `appointment` | `vLastName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 57 | text column with distinct count 57 <= threshold 500 |
| `appointment` | `vPreferredLanguage` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | text column with distinct count 1 <= threshold 500 |
| `appointment` | `vRecordedFIle` | `VARCHAR(500) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | text column with distinct count 1 <= threshold 500 |
| `appointment` | `vRejected_By` | `VARCHAR(30) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | text column with distinct count 1 <= threshold 500 |
| `appointment` | `vThumbnail` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 0 | text column with distinct count 0 <= threshold 500 |
| `appointment_parties` | `vPartyName` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 25 | text column with distinct count 25 <= threshold 500 |
| `appointment_parties` | `vPartyNo` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 4 | text column with distinct count 4 <= threshold 500 |
| `appointment_parties` | `vRelationship` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 20 | text column with distinct count 20 <= threshold 500 |
| `assign_talent` | `eBilingType` | `ENUM` (options: Per Hour, Per Event) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `assign_talent` | `eEmailStatus` | `VARCHAR(32) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 0 | low-cardinality values (0) appear non-PII; manual review recommended |
| `assign_talent` | `eNewStatus` | `ENUM` (options: assign, pending, notify, caneled, booked, none, not assigned) | **VALUE_LOW** | 7 | declared option count 7 <= threshold 500 |
| `assign_talent` | `eRecurring` | `ENUM` (options: yes) | **VALUE_LOW** | 1 | declared option count 1 <= threshold 500 |
| `assign_talent` | `eStatus` | `ENUM` (options: assign, pending, canceled, booked, none) | **VALUE_LOW** | 5 | declared option count 5 <= threshold 500 |
| `assign_talent` | `eTalentEmailStatus` | `VARCHAR(32) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 0 | low-cardinality values (0) appear non-PII; manual review recommended |
| `assign_talent` | `eTalentFeeType` | `ENUM` (options: Per Hour, Per Event) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `assign_talent` | `eTalentPaid` | `ENUM` (options: yes, no) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `assign_talent` | `eTalentStatus` | `ENUM` (options: pending, active, canceled, completed, refunded) | **VALUE_LOW** | 5 | declared option count 5 <= threshold 500 |
| `assign_talent` | `eTalentStopReminder` | `ENUM` (options: Open, Closed) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `assign_talent` | `tTalentRequirements` | `TEXT COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 24 | text column with distinct count 24 <= threshold 500 |
| `auto_register_santa_schedule` | `eEmailStatus` | `ENUM` (options: pending, delivered, failed) | **VALUE_LOW** | 3 | declared option count 3 <= threshold 500 |
| `auto_register_santa_schedule` | `vData` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 25 | text column with distinct count 25 <= threshold 500 |
| `buckets` | `vBucketName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 5 | text column with distinct count 5 <= threshold 500 |
| `calendar_auth_detail` | `eCalStatus` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `calendar_auth_detail` | `eHsssStatus` | `ENUM` (options: saved, notsaved) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `calendar_auth_detail` | `vResourceUri` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | text column with distinct count 1 <= threshold 500 |
| `calendar_auth_detail` | `vUUID` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | text column with distinct count 1 <= threshold 500 |
| `call_event_logs` | `tEventMsg` | `TEXT COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 0 | text column with distinct count 0 <= threshold 500 |
| `call_event_logs` | `vEvent` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 0 | text column with distinct count 0 <= threshold 500 |
| `children` | `eGender` | `ENUM` (options: Male, Female, Other) | **VALUE_LOW** | 3 | declared option count 3 <= threshold 500 |
| `children` | `vAccomplishments` | `VARCHAR(500) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 18 | text column with distinct count 18 <= threshold 500 |
| `children` | `vChildLocation` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 27 | text column with distinct count 27 <= threshold 500 |
| `children` | `vChildName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 140 | text column with distinct count 140 <= threshold 500 |
| `children` | `vChildNamePronunciation` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 118 | text column with distinct count 118 <= threshold 500 |
| `children` | `vEncouragementToImprove` | `VARCHAR(500) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 19 | text column with distinct count 19 <= threshold 500 |
| `children` | `vGifts` | `VARCHAR(500) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 21 | text column with distinct count 21 <= threshold 500 |
| `children` | `vGrade` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 27 | text column with distinct count 27 <= threshold 500 |
| `children` | `vPetsInfo` | `VARCHAR(500) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 17 | text column with distinct count 17 <= threshold 500 |
| `children` | `vSchool` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 24 | text column with distinct count 24 <= threshold 500 |
| `children` | `vTeacherName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 20 | text column with distinct count 20 <= threshold 500 |
| `client` | `eEmailListed` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `client` | `eMobileListed` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `client` | `ePhnHomeListed` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `client` | `ePhnOffcListed` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `client` | `ePhnOtherListed` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `client` | `eStatus` | `ENUM` (options: Disabled, Enabled, Deleted) | **VALUE_LOW** | 3 | declared option count 3 <= threshold 500 |
| `client` | `eTitle` | `ENUM` (options: Mr., Mrs., Miss, Ms) | **VALUE_LOW** | 4 | declared option count 4 <= threshold 500 |
| `client` | `eWebListed` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `client` | `vCity` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 23 | text column with distinct count 23 <= threshold 500 |
| `client` | `vCompanyName` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 11 | text column with distinct count 11 <= threshold 500 |
| `client` | `vFirstName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 27 | text column with distinct count 27 <= threshold 500 |
| `client` | `vLastName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 30 | text column with distinct count 30 <= threshold 500 |
| `client` | `vMidName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 2 | text column with distinct count 2 <= threshold 500 |
| `client` | `vNickName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | text column with distinct count 1 <= threshold 500 |
| `client` | `vPhnHomeExt` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | text column with distinct count 1 <= threshold 500 |
| `client` | `vPhnOffcExt` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | text column with distinct count 1 <= threshold 500 |
| `client` | `vPhnOtherExt` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | text column with distinct count 1 <= threshold 500 |
| `client` | `vPhoneOther` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | low-cardinality values (1) appear non-PII; manual review recommended |
| `client` | `vWebsite` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | text column with distinct count 1 <= threshold 500 |
| `client` | `vZipCode` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 27 | text column with distinct count 27 <= threshold 500 |
| `countries` | `country_name` | `VARCHAR(150) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 246 | text column with distinct count 246 <= threshold 500 |
| `countries` | `sortname` | `VARCHAR(3) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 246 | text column with distinct count 246 <= threshold 500 |
| `email_logs` | `eDeleteStatus` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `email_logs` | `eMailStatus` | `VARCHAR(32) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 3 | text column with distinct count 3 <= threshold 500 |
| `email_logs` | `vEmailTo` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 0 | low-cardinality values (0) appear non-PII; manual review recommended |
| `email_logs` | `vPurpose` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 18 | text column with distinct count 18 <= threshold 500 |
| `email_logs` | `vRecipient` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 97 | text column with distinct count 97 <= threshold 500 |
| `email_logs` | `vSubject` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 298 | text column with distinct count 298 <= threshold 500 |
| `email_templates` | `eStatus` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `email_templates` | `eTemplateFor` | `ENUM` (options: user, santa, admin, common) | **VALUE_LOW** | 4 | declared option count 4 <= threshold 500 |
| `email_templates` | `vEmailSubject` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 56 | low-cardinality values (56) appear non-PII; manual review recommended |
| `email_templates` | `vTemplateName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 59 | text column with distinct count 59 <= threshold 500 |
| `email_templates_2026(bk)` | `eStatus` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `email_templates_2026(bk)` | `eTemplateFor` | `ENUM` (options: user, santa, admin, common) | **VALUE_LOW** | 4 | declared option count 4 <= threshold 500 |
| `email_templates_2026(bk)` | `vEmailSubject` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 55 | low-cardinality values (55) appear non-PII; manual review recommended |
| `email_templates_2026(bk)` | `vTemplateName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 59 | text column with distinct count 59 <= threshold 500 |
| `email_templates_bk2025` | `eStatus` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `email_templates_bk2025` | `eTemplateFor` | `ENUM` (options: user, santa, admin, common, client) | **VALUE_LOW** | 5 | declared option count 5 <= threshold 500 |
| `email_templates_bk2025` | `vEmailSubject` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 53 | low-cardinality values (53) appear non-PII; manual review recommended |
| `email_templates_bk2025` | `vTemplateName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 57 | text column with distinct count 57 <= threshold 500 |
| `email_templates_prev` | `eStatus` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `email_templates_prev` | `eTemplateFor` | `ENUM` (options: user, santa, admin, common, client) | **VALUE_LOW** | 5 | declared option count 5 <= threshold 500 |
| `email_templates_prev` | `vEmailSubject` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 51 | low-cardinality values (51) appear non-PII; manual review recommended |
| `email_templates_prev` | `vTemplateName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 55 | text column with distinct count 55 <= threshold 500 |
| `event` | `eEventStatus` | `ENUM` (options: pending, active, canceled, completed) | **VALUE_LOW** | 4 | declared option count 4 <= threshold 500 |
| `event` | `eStopReminder` | `ENUM` (options: Open, Closed) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `event` | `tCancelReason` | `TEXT COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 0 | text column with distinct count 0 <= threshold 500 |
| `event` | `vEventName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 384 | text column with distinct count 384 <= threshold 500 |
| `event_assign_schedule` | `eAssignType` | `ENUM` (options: book, confirm, notify, reassign) | **VALUE_LOW** | 4 | declared option count 4 <= threshold 500 |
| `event_assign_schedule` | `eEmailStatus` | `VARCHAR(32) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 3 | low-cardinality values (3) appear non-PII; manual review recommended |
| `event_assign_schedule` | `eSmsStatus` | `ENUM` (options: delivered, pending, failed) | **VALUE_LOW** | 3 | declared option count 3 <= threshold 500 |
| `event_assign_schedule` | `eTalentType` | `ENUM` (options: Santa, Mrs Claus, Live Reindeer, Mascots, Elf, Photographer, Easter Bunny, Face Painter, Balloon Artist, Other, Misc Charge) | **VALUE_LOW** | 11 | declared option count 11 <= threshold 500 |
| `event_details` | `assignednotes` | `TEXT COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 4 | text column with distinct count 4 <= threshold 500 |
| `event_details` | `beginTime` | `VARCHAR(10) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 15 | text column with distinct count 15 <= threshold 500 |
| `event_details` | `endTime` | `VARCHAR(10) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 18 | text column with distinct count 18 <= threshold 500 |
| `event_details` | `eventName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 27 | text column with distinct count 27 <= threshold 500 |
| `event_details` | `latitude` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 12 | text column with distinct count 12 <= threshold 500 |
| `event_details` | `locationCity` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 14 | text column with distinct count 14 <= threshold 500 |
| `event_details` | `locationState` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 10 | text column with distinct count 10 <= threshold 500 |
| `event_details` | `locationZip` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 14 | text column with distinct count 14 <= threshold 500 |
| `event_details` | `longitude` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 9 | text column with distinct count 9 <= threshold 500 |
| `event_details` | `payRate` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 26 | text column with distinct count 26 <= threshold 500 |
| `event_location` | `eBookingStatus` | `ENUM` (options: pending, active, canceled, completed, refunded) | **VALUE_LOW** | 5 | declared option count 5 <= threshold 500 |
| `event_location` | `eSameLocation` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `event_location` | `eSessionType` | `ENUM` (options: recurring, nonrecurring) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `event_location` | `eStatus` | `ENUM` (options: Disabled, Enabled, Delete) | **VALUE_LOW** | 3 | declared option count 3 <= threshold 500 |
| `event_location` | `eTalentStatus` | `ENUM` (options: issue, assigned, none(Waiting for payment), booked) | **VALUE_LOW** | 4 | declared option count 4 <= threshold 500 |
| `event_location` | `iTotalHrs` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 187 | text column with distinct count 187 <= threshold 500 |
| `event_location` | `tCancelBookingReason` | `TEXT COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 11 | text column with distinct count 11 <= threshold 500 |
| `event_location` | `vCity` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 24 | text column with distinct count 24 <= threshold 500 |
| `event_location` | `vContactPerson` | `VARCHAR(120) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 45 | low-cardinality values (45) appear non-PII; manual review recommended |
| `event_location` | `vLatitude` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 9 | text column with distinct count 9 <= threshold 500 |
| `event_location` | `vLongitude` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 9 | text column with distinct count 9 <= threshold 500 |
| `event_location` | `vSelectedDays` | `VARCHAR(225) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 0 | text column with distinct count 0 <= threshold 500 |
| `event_location` | `vZipCode` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 27 | text column with distinct count 27 <= threshold 500 |
| `event_location_recurring` | `vDay` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 7 | text column with distinct count 7 <= threshold 500 |
| `event_notifications` | `eAdmin` | `ENUM` (options: 1, 0) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `event_notifications` | `eEmail` | `ENUM` (options: 1, 0) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `event_notifications` | `eSMS` | `ENUM` (options: 1, 0) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `event_notifications` | `eSanta` | `ENUM` (options: 1, 0) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `event_notifications` | `eUser` | `ENUM` (options: 1, 0) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `event_notifications` | `vNotificationName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 17 | text column with distinct count 17 <= threshold 500 |
| `global_settings` | `eIsVisible` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `global_settings` | `vSettingValue` | `VARCHAR(2000) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 26 | text column with distinct count 26 <= threshold 500 |
| `google_events` | `eEventType` | `ENUM` (options: hiresanta, googlecalendar) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `google_events` | `vEventLocation` | `VARCHAR(225) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 4 | text column with distinct count 4 <= threshold 500 |
| `google_events` | `vStatus` | `ENUM` (options: confirmed, cancelled) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `google_events` | `vTimeZone` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 4 | text column with distinct count 4 <= threshold 500 |
| `invoice` | `eBilingType` | `ENUM` (options: Per Hour, Per Event) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `invoice` | `eDiscountType` | `ENUM` (options: percentage, amount) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `invoice` | `eEmailStatus` | `VARCHAR(32) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 0 | low-cardinality values (0) appear non-PII; manual review recommended |
| `invoice` | `eInvoiceFor` | `ENUM` (options: talent, client) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `invoice` | `eInvoiceGenerateType` | `ENUM` (options: general, normal) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `invoice` | `eInvoiceStatus` | `ENUM` (options: pending, sent, paid, unpaid, partial paid, fully paid, refunded, save as draft, under contract, viewed, partial refund, cancelled, extra paid) | **VALUE_LOW** | 13 | declared option count 13 <= threshold 500 |
| `invoice` | `eInvoiceType` | `ENUM` (options: Regular, Contract, Manual) | **VALUE_LOW** | 3 | declared option count 3 <= threshold 500 |
| `invoice` | `eNoSalesTax` | `ENUM` (options: off, on) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `invoice` | `eOldInvoiceStatus` | `ENUM` (options: pending, sent, paid, unpaid, partial paid, fully paid, refunded, save as draft, under contract, viewed, partial refund, cancelled, extra paid) | **VALUE_LOW** | 13 | declared option count 13 <= threshold 500 |
| `invoice` | `eRequiredAmountType` | `ENUM` (options: percentage, amount) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `invoice` | `eRequiredType` | `ENUM` (options: default, multiple) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `invoice` | `vInvoiceNo` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 381 | text column with distinct count 381 <= threshold 500 |
| `invoice` | `vPurchaseOrder` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 6 | text column with distinct count 6 <= threshold 500 |
| `invoice_due_date` | `eCreatedType` | `ENUM` (options: manual, automatic, change) | **VALUE_LOW** | 3 | declared option count 3 <= threshold 500 |
| `invoice_due_date` | `eHideBox` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `invoice_due_date` | `ePaidStatus` | `ENUM` (options: paid, pending) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `invoice_payment` | `ePaymentMode` | `ENUM` (options: ach/wire, check, other, online) | **VALUE_LOW** | 4 | declared option count 4 <= threshold 500 |
| `invoice_payment` | `eRefundMode` | `ENUM` (options: ach/wire, check, other, online) | **VALUE_LOW** | 4 | declared option count 4 <= threshold 500 |
| `invoice_payment` | `eRefunded` | `ENUM` (options: Yes, No) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `invoice_payment` | `eType` | `ENUM` (options: payment, refund) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `invoice_payment` | `is_fully_refunded` | `ENUM` (options: yes, no) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `invoice_payment` | `vChequeNumber` | `VARCHAR(225) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 31 | text column with distinct count 31 <= threshold 500 |
| `invoice_payment` | `vPaymentStatus` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | text column with distinct count 1 <= threshold 500 |
| `invoice_payment` | `vRefundAmount` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 28 | text column with distinct count 28 <= threshold 500 |
| `invoice_payment` | `vRefundChequeNumber` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 31 | text column with distinct count 31 <= threshold 500 |
| `invoice_reminder` | `eStatus` | `ENUM` (options: Sent, Enqueued, Error) | **VALUE_LOW** | 3 | declared option count 3 <= threshold 500 |
| `invoice_save` | `eBilingType` | `ENUM` (options: Per Hour, Per Event) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `invoice_save` | `eDiscountType` | `ENUM` (options: percentage, amount) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `invoice_save` | `eInvoiceFor` | `ENUM` (options: talent, client) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `invoice_save` | `eInvoiceStatus` | `ENUM` (options: pending, sent, paid, unpaid, partial paid, fully paid, refunded, save) | **VALUE_LOW** | 8 | declared option count 8 <= threshold 500 |
| `invoice_save` | `eInvoiceType` | `ENUM` (options: Regular, Contract) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `invoice_save` | `vInvoiceNo` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 102 | text column with distinct count 102 <= threshold 500 |
| `log_messages` | `eLogType` | `ENUM` (options: create_booking, update_booking, assign_talent, reassign_talent, remove_talent, send_invoice, update_invoice, save_invoice, delete_event, delete_location, complete_event, add_payment, refund_payment, resend_invoice, notify_talent, pending_talent) | **VALUE_LOW** | 16 | declared option count 16 <= threshold 500 |
| `notifications` | `eIsRead` | `ENUM` (options: Read, Not Read) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `payment` | `eRefundBy` | `ENUM` (options: admin, user) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `payment` | `vCurrency` | `VARCHAR(10) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | text column with distinct count 1 <= threshold 500 |
| `payment` | `vPaymentStatus` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 2 | text column with distinct count 2 <= threshold 500 |
| `payment` | `vRefundStatus` | `VARCHAR(70) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 2 | text column with distinct count 2 <= threshold 500 |
| `promo_codes` | `eDiscountType` | `ENUM` (options: percent, fixed) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `promo_codes` | `ePromoCodeType` | `ENUM` (options: personalized_call, live_video_call, both) | **VALUE_LOW** | 3 | declared option count 3 <= threshold 500 |
| `promo_codes` | `eStatus` | `ENUM` (options: enabled, disabled) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `promo_codes` | `vPromoCode` | `VARCHAR(20) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 14 | text column with distinct count 14 <= threshold 500 |
| `promo_codes` | `vPromoName` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 8 | text column with distinct count 8 <= threshold 500 |
| `promocode_tracker` | `ePromocodeUsed` | `ENUM` (options: used, applied) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `rejected_log` | `eRejectedByType` | `ENUM` (options: admin, santa, user) | **VALUE_LOW** | 3 | declared option count 3 <= threshold 500 |
| `reschedule_logs` | `eAppointmentType` | `ENUM` (options: no_show, personalize_user) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `reschedule_logs` | `tAppointmentData` | `TEXT` | **VALUE_LOW** | 14 | text column with distinct count 14 <= threshold 500 |
| `retail_affiliates` | `eStatus` | `ENUM` (options: Enabled, Disabled) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `retail_affiliates` | `vCompanyName` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 8 | text column with distinct count 8 <= threshold 500 |
| `retail_affiliates` | `vFirstName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 9 | text column with distinct count 9 <= threshold 500 |
| `retail_affiliates` | `vLastName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 8 | text column with distinct count 8 <= threshold 500 |
| `santa_details` | `eMarkAsPCR` | `ENUM` (options: 1, 0) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `santa_details` | `eScreeningStatus` | `ENUM` (options: approved, disapproved) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `santa_details` | `vDayContactNumber` | `VARCHAR(20) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | low-cardinality values (1) appear non-PII; manual review recommended |
| `santa_details` | `vEnglishFluency` | `ENUM` (options: Fluent, Beginner, Average, No) | **VALUE_LOW** | 4 | declared option count 4 <= threshold 500 |
| `santa_details` | `vEveningContactNumber` | `VARCHAR(20) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | low-cardinality values (1) appear non-PII; manual review recommended |
| `santa_details` | `vExperience` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | text column with distinct count 1 <= threshold 500 |
| `santa_details` | `vSpanishFluency` | `ENUM` (options: Fluent, Beginner, Average, No) | **VALUE_LOW** | 4 | declared option count 4 <= threshold 500 |
| `santa_emergency_contact` | `vSantaName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 6 | text column with distinct count 6 <= threshold 500 |
| `santa_emergency_contact` | `vSantaRating` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 8 | text column with distinct count 8 <= threshold 500 |
| `santa_screening_data` | `eEnglishLanguage` | `ENUM` (options: Fluent, Beginner, Average, No) | **VALUE_LOW** | 4 | declared option count 4 <= threshold 500 |
| `santa_screening_data` | `eSantaDress` | `ENUM` (options: yes, no) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `santa_screening_data` | `eSpanishLanguage` | `ENUM` (options: Fluent, Beginner, Average, No) | **VALUE_LOW** | 4 | declared option count 4 <= threshold 500 |
| `santa_screening_data` | `eStatus` | `ENUM` (options: in_review, rejected, pending, accepted) | **VALUE_LOW** | 4 | declared option count 4 <= threshold 500 |
| `santa_screening_data` | `iBrowserCheck` | `ENUM` (options: passed, failed) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `santa_screening_data` | `iCameraCheck` | `ENUM` (options: passed, failed) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `santa_screening_data` | `iMicrophoneCheck` | `ENUM` (options: passed, failed) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `santa_screening_data` | `iSpeedTest` | `ENUM` (options: passed, failed) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `santa_screening_data` | `tSantaDressAssets` | `TEXT COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 8 | text column with distinct count 8 <= threshold 500 |
| `santa_screening_data` | `tScreeningVideo` | `MEDIUMTEXT` | **VALUE_LOW** | 3 | text column with distinct count 3 <= threshold 500 |
| `santa_screening_data` | `vBrowserName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 2 | text column with distinct count 2 <= threshold 500 |
| `santa_screening_data` | `vSpeed` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 11 | text column with distinct count 11 <= threshold 500 |
| `santas_finder_details` | `FirstName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 4 | text column with distinct count 4 <= threshold 500 |
| `santas_finder_details` | `LastName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 3 | text column with distinct count 3 <= threshold 500 |
| `santas_finder_details` | `TimeZone` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | text column with distinct count 1 <= threshold 500 |
| `santas_finder_details` | `latitude` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 5 | text column with distinct count 5 <= threshold 500 |
| `santas_finder_details` | `longitude` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 5 | text column with distinct count 5 <= threshold 500 |
| `schedule_email_notifications` | `eReceiverType` | `ENUM` (options: location, user, admin, santa, appointment, retail) | **VALUE_LOW** | 6 | declared option count 6 <= threshold 500 |
| `schedule_email_notifications` | `eSendingFrom` | `ENUM` (options: MAILGUN, MAILCHIMP) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `schedule_email_notifications` | `eStatus` | `ENUM` (options: Enqueued, Sent, Error) | **VALUE_LOW** | 3 | declared option count 3 <= threshold 500 |
| `schedule_events` | `eTalentType` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 8 | text column with distinct count 8 <= threshold 500 |
| `schedule_events` | `emailStatus` | `ENUM` (options: delivered, pending, failed) | **VALUE_LOW** | 3 | declared option count 3 <= threshold 500 |
| `schedule_events` | `santaPostalCode` | `VARCHAR(15) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 13 | text column with distinct count 13 <= threshold 500 |
| `schedule_events` | `santaTimeZone` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 4 | text column with distinct count 4 <= threshold 500 |
| `schedule_events` | `smsStatus` | `ENUM` (options: delivered, pending, failed) | **VALUE_LOW** | 3 | declared option count 3 <= threshold 500 |
| `schedule_events` | `snataName` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 27 | text column with distinct count 27 <= threshold 500 |
| `schedule_sms_notifications` | `eReceiverType` | `ENUM` (options: location, user, admin, santa, appointment) | **VALUE_LOW** | 5 | declared option count 5 <= threshold 500 |
| `schedule_sms_notifications` | `eStatus` | `ENUM` (options: Enqueued, Sent, Error) | **VALUE_LOW** | 3 | declared option count 3 <= threshold 500 |
| `schedule_system_logs` | `vEventName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 288 | text column with distinct count 288 <= threshold 500 |
| `screening_steps` | `eStep` | `ENUM` (options: step_one, step_two, step_three, step_four, completed) | **VALUE_LOW** | 5 | declared option count 5 <= threshold 500 |
| `sms_templates` | `eStatus` | `ENUM` (options: 1, 0) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `sms_templates` | `eTemplateFor` | `ENUM` (options: user, santa, admin, common) | **VALUE_LOW** | 4 | declared option count 4 <= threshold 500 |
| `states` | `eStatus` | `ENUM` (options: active, inactive) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `states` | `vStateCode` | `VARCHAR(100)` | **VALUE_LOW** | 57 | text column with distinct count 57 <= threshold 500 |
| `states` | `vStateName` | `VARCHAR(200)` | **VALUE_LOW** | 57 | text column with distinct count 57 <= threshold 500 |
| `static_pages` | `tPageSlug` | `TEXT COLLATE utf8mb4_unicode_520_ci` | **VALUE_LOW** | 2 | text column with distinct count 2 <= threshold 500 |
| `static_pages` | `vPageName` | `VARCHAR(100) COLLATE utf8mb3_unicode_ci` | **VALUE_LOW** | 2 | text column with distinct count 2 <= threshold 500 |
| `talent_person_details` | `eAccountType` | `ENUM` (options: Checking, Savings) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `talent_person_details` | `eStatus` | `ENUM` (options: Disabled, Enabled) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `talent_person_details` | `latitude` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 2 | text column with distinct count 2 <= threshold 500 |
| `talent_person_details` | `longitude` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 2 | text column with distinct count 2 <= threshold 500 |
| `talent_person_details` | `tAddress` | `TEXT COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 12 | low-cardinality values (12) appear non-PII; manual review recommended |
| `talent_person_details` | `vAccountNumber` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 6 | text column with distinct count 6 <= threshold 500 |
| `talent_person_details` | `vBankName` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | text column with distinct count 1 <= threshold 500 |
| `talent_person_details` | `vCity` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 12 | text column with distinct count 12 <= threshold 500 |
| `talent_person_details` | `vFirstName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 29 | text column with distinct count 29 <= threshold 500 |
| `talent_person_details` | `vLastName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 29 | text column with distinct count 29 <= threshold 500 |
| `talent_person_details` | `vOtherPayType` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | text column with distinct count 1 <= threshold 500 |
| `talent_person_details` | `vRoutingNumber` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 6 | text column with distinct count 6 <= threshold 500 |
| `talent_person_details` | `vZipcode` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 4 | text column with distinct count 4 <= threshold 500 |
| `talent_type` | `eStatus` | `ENUM` (options: active, inactive) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `talent_type` | `vTalentType` | `VARCHAR(120) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 13 | text column with distinct count 13 <= threshold 500 |
| `user_timezones` | `vTimeZone` | `VARCHAR(11) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 33 | text column with distinct count 33 <= threshold 500 |
| `user_timezones` | `vTimeZoneAbv` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 91 | text column with distinct count 91 <= threshold 500 |
| `user_timezones` | `vTimeZoneDST` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | text column with distinct count 1 <= threshold 500 |
| `user_timezones` | `vTimeZoneName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 91 | text column with distinct count 91 <= threshold 500 |
| `users` | `eAccountType` | `ENUM` (options: Checking, Savings) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `users` | `eAuditionStatus` | `ENUM` (options: byPass) | **VALUE_LOW** | 1 | declared option count 1 <= threshold 500 |
| `users` | `eEmailListed` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `users` | `eGender` | `ENUM` (options: Male, Female, Other) | **VALUE_LOW** | 3 | declared option count 3 <= threshold 500 |
| `users` | `eIsGoogleCalendar` | `ENUM` (options: yes, no) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `users` | `eMobileListed` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `users` | `ePhnHomeListed` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `users` | `ePhnOffcListed` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `users` | `ePhnOtherListed` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `users` | `eRegisterType` | `ENUM` (options: autoRegister) | **VALUE_LOW** | 1 | declared option count 1 <= threshold 500 |
| `users` | `eStatus` | `ENUM` (options: Disabled, Enabled) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `users` | `eUserType` | `ENUM` (options: User, Santa) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `users` | `eVerified` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `users` | `eWebListed` | `ENUM` (options: 0, 1) | **VALUE_LOW** | 2 | declared option count 2 <= threshold 500 |
| `users` | `iSeasonState` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 0 | text column with distinct count 0 <= threshold 500 |
| `users` | `iZipCode` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 26 | text column with distinct count 26 <= threshold 500 |
| `users` | `isAffiliated` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 1 | text column with distinct count 1 <= threshold 500 |
| `users` | `latitude` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 9 | text column with distinct count 9 <= threshold 500 |
| `users` | `longitude` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 9 | text column with distinct count 9 <= threshold 500 |
| `users` | `vAccountNumber` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 9 | text column with distinct count 9 <= threshold 500 |
| `users` | `vAffiliateCode` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 0 | text column with distinct count 0 <= threshold 500 |
| `users` | `vAltUserMail` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 9 | text column with distinct count 9 <= threshold 500 |
| `users` | `vBankName` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 2 | text column with distinct count 2 <= threshold 500 |
| `users` | `vCity` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 21 | text column with distinct count 21 <= threshold 500 |
| `users` | `vFirstName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 100 | text column with distinct count 100 <= threshold 500 |
| `users` | `vLastName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 81 | text column with distinct count 81 <= threshold 500 |
| `users` | `vOtherPayType` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 4 | text column with distinct count 4 <= threshold 500 |
| `users` | `vPhnHomeExt` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 3 | text column with distinct count 3 <= threshold 500 |
| `users` | `vPhnOffcExt` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 3 | text column with distinct count 3 <= threshold 500 |
| `users` | `vPhnOtherExt` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 3 | text column with distinct count 3 <= threshold 500 |
| `users` | `vProfilePic` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 12 | text column with distinct count 12 <= threshold 500 |
| `users` | `vRoutingNumber` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 8 | text column with distinct count 8 <= threshold 500 |
| `users` | `vSeasonAddress` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 0 | low-cardinality values (0) appear non-PII; manual review recommended |
| `users` | `vSeasonCity` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 0 | text column with distinct count 0 <= threshold 500 |
| `users` | `vSeasonZip` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 0 | text column with distinct count 0 <= threshold 500 |
| `users` | `vState` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 18 | text column with distinct count 18 <= threshold 500 |
| `users` | `vWebsite` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_LOW** | 3 | text column with distinct count 3 <= threshold 500 |
| `santas_finder_details` | `PostalCode` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **VALUE_HIGH** | 501 | text column with distinct count 501 > threshold 500 (short length) |
| `abandoned_mail_sent` | `dCreatedDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `abandoned_mail_sent` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `abandoned_mail_sent` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `abandoned_mail_sent` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `access_permission` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `access_permission` | `iAccessId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `access_permission` | `iChild` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `access_permission` | `iMenu` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `access_permission` | `iOrderId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `access_permission` | `iParentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `access_permission_bk(01apr2024)` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `access_permission_bk(01apr2024)` | `iAccessId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `access_permission_bk(01apr2024)` | `iChild` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `access_permission_bk(01apr2024)` | `iMenu` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `access_permission_bk(01apr2024)` | `iOrderId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `access_permission_bk(01apr2024)` | `iParentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `admin` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `admin` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `admin_bk(28mar2024)` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `admin_bk(28mar2024)` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `affiliate_codes` | `bDeleted` | `TINYINT` | **SKIP** | - | non-text type: TINYINT |
| `affiliate_codes` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `affiliate_codes` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `affiliate_codes` | `dValidFrom` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `affiliate_codes` | `dValidTill` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `affiliate_codes` | `fAmount` | `DECIMAL(8, 2)` | **SKIP** | - | non-text type: DECIMAL(8, 2) |
| `affiliate_codes` | `fCommissionFee` | `DECIMAL(8, 2)` | **SKIP** | - | non-text type: DECIMAL(8, 2) |
| `affiliate_codes` | `fLiveCallPrice` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `affiliate_codes` | `fPreRecodeVideoPrice` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `affiliate_codes` | `iAffiliateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `affiliate_codes` | `iClicks` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `affiliate_codes` | `iConverted` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `affiliate_codes` | `iSantaId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `affiliate_tracker` | `fCommissionFee` | `DECIMAL(8, 2)` | **SKIP** | - | non-text type: DECIMAL(8, 2) |
| `affiliate_tracker` | `iAffiliateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `affiliate_tracker` | `iSantaId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `affiliate_tracker` | `iTrackerId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `affiliate_tracker` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment` | `bIsSantaMissed` | `TINYINT` | **SKIP** | - | non-text type: TINYINT |
| `appointment` | `bIsUserMissed` | `TINYINT` | **SKIP** | - | non-text type: TINYINT |
| `appointment` | `dAppointmentDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `appointment` | `dCallEndTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `appointment` | `dCallStartTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `appointment` | `dChildReminder` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `appointment` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `appointment` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `appointment` | `fAppointmentFee` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `appointment` | `fDiscountFee` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `appointment` | `fTax` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `appointment` | `iAffiliateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment` | `iCountryId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment` | `iOldSantaId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment` | `iPin` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `appointment` | `iPromoCodeId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment` | `iSantaId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment` | `timezone` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `appointment` | `vArchiveId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment` | `vTokboxId` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment_parties` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `appointment_parties` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment_parties` | `iCountryId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment_parties` | `iPartyId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment_parties` | `iPin` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `appointment_parties` | `iTimeZoneId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `assign_access_permission` | `iAccessId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `assign_access_permission` | `iAssignId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `assign_access_permission` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `assign_access_permission_bk(28mar2024)` | `iAccessId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `assign_access_permission_bk(28mar2024)` | `iAssignId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `assign_access_permission_bk(28mar2024)` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `assign_talent` | `dAssignNotifyDateTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `assign_talent` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `assign_talent` | `dEndTime` | `TIME` | **SKIP** | - | non-text type: TIME |
| `assign_talent` | `dLastClientReminderAttempt` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `assign_talent` | `dLastClientReminderDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `assign_talent` | `dLastReminderAttempt` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `assign_talent` | `dLastReminderDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `assign_talent` | `dStartTime` | `TIME` | **SKIP** | - | non-text type: TIME |
| `assign_talent` | `dTalenPaidDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `assign_talent` | `dTalentStartDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `assign_talent` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `assign_talent` | `fNewPrice` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `assign_talent` | `fPrice` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `assign_talent` | `fTalentFee` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `assign_talent` | `fTotalPrice` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `assign_talent` | `iClientReminderRetryCount` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `assign_talent` | `iEventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `assign_talent` | `iEventLocationId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `assign_talent` | `iEventLocationRecId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `assign_talent` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `assign_talent` | `iInvoiceId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `assign_talent` | `iNewSantaId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `assign_talent` | `iReminderCount` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `assign_talent` | `iReminderRetryCount` | `TINYINT` | **SKIP** | - | non-text type: TINYINT |
| `assign_talent` | `iSantaId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `assign_talent` | `iTalentPersonId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `assign_talent` | `iTalentTypeId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `assign_talent` | `iTotal` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `assign_talent` | `tAssignedPerfomerComment` | `LONGTEXT` | **SKIP** | - | free-text name pattern: 'comment' |
| `assign_talent` | `tItemsDescription` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'description' |
| `assign_talent` | `tPerfomerComment` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'comment' |
| `assign_talent` | `vMailgunId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `assign_talent` | `vTalentMailgunId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `auto_register_santa_schedule` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `auto_register_santa_schedule` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `auto_register_santa_schedule` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `auto_register_santa_schedule` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `availability` | `dAvailableDateTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `availability` | `dAvailableUTCDateTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `availability` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `availability` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `availability` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `availability` | `iTalentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `booking_slots` | `dStartTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `booking_slots` | `iBookings` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `booking_slots` | `iSlotId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `buckets` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `buckets` | `eBucketPriority` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `buckets` | `iBucketId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `calendar_auth_detail` | `dCalendarWatch` | `DATE` | **SKIP** | - | non-text type: DATE |
| `calendar_auth_detail` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `calendar_auth_detail` | `dUpdatedDtae` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `calendar_auth_detail` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `calendar_auth_detail` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `calendar_auth_detail` | `vCalendarId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `calendar_auth_detail` | `vResourceId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `call_event_logs` | `dEventCreateAt` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `call_event_logs` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `call_event_logs` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `call_logs` | `dBufferStartTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `call_logs` | `dCallStartTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `call_logs` | `dSantaJoined` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `call_logs` | `dUserJoined` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `call_logs` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `call_logs` | `ilogId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `children` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `children` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `children` | `iChildId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `children` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `children` | `tOtherNotes` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'notes' |
| `client` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `client` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `client` | `iClientId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `client` | `iPhnHomeCode` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `client` | `iPhnOfficeCode` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `client` | `iPhnOtherCode` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `client` | `iStateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `client` | `vClientHubSpotId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `countries` | `id` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `day_pricing` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `day_pricing` | `dDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `day_pricing` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `day_pricing` | `fPCPrice` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `day_pricing` | `fVCPrice` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `day_pricing` | `iDayPriceId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `email_logs` | `dCreatedAt` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `email_logs` | `dUpdatedAt` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `email_logs` | `iEventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `email_logs` | `iLogId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `email_logs` | `vMailgunMessageId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `email_templates` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `email_templates` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `email_templates` | `iTemplateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `email_templates` | `tNote` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'note' |
| `email_templates` | `tTemplateContent` | `LONGTEXT` | **SKIP** | - | free-text name pattern: 'content' |
| `email_templates_2026(bk)` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `email_templates_2026(bk)` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `email_templates_2026(bk)` | `iTemplateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `email_templates_2026(bk)` | `tNote` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'note' |
| `email_templates_2026(bk)` | `tTemplateContent` | `LONGTEXT` | **SKIP** | - | free-text name pattern: 'content' |
| `email_templates_bk2025` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `email_templates_bk2025` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `email_templates_bk2025` | `iTemplateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `email_templates_bk2025` | `tNote` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'note' |
| `email_templates_bk2025` | `tTemplateContent` | `LONGTEXT` | **SKIP** | - | free-text name pattern: 'content' |
| `email_templates_prev` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `email_templates_prev` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `email_templates_prev` | `iTemplateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `email_templates_prev` | `tNote` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'note' |
| `email_templates_prev` | `tTemplateContent` | `LONGTEXT` | **SKIP** | - | free-text name pattern: 'content' |
| `event` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event` | `dFollowUpReminder` | `DATE` | **SKIP** | - | non-text type: DATE |
| `event` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event` | `fDiscountFee` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `event` | `fEventFee` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `event` | `fShippingFee` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `event` | `fTax` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `event` | `iClientId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event` | `iEventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event` | `tBookingComment` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'comment' |
| `event` | `tPerfomerComment` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'comment' |
| `event_assign_schedule` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_assign_schedule` | `dSmsSentDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_assign_schedule` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_assign_schedule` | `iEventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_assign_schedule` | `iEventLocationId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_assign_schedule` | `iSantaId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_assign_schedule` | `iScheduleIdId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_assign_schedule` | `iTalentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_assign_schedule` | `vMailgunId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_assign_schedule` | `vSmsFailMessage` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'message' |
| `event_details` | `createdDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_details` | `eventDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `event_details` | `eventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_details` | `notes` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'notes' |
| `event_details` | `updatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_location` | `dAssignTalentMailSentDatetime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_location` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_location` | `dEndTime` | `TIME` | **SKIP** | - | non-text type: TIME |
| `event_location` | `dEventDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `event_location` | `dLastReminderDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `event_location` | `dRepeatUntilDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `event_location` | `dStartTime` | `TIME` | **SKIP** | - | non-text type: TIME |
| `event_location` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_location` | `iAltCountryCode` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `event_location` | `iCountryCode` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `event_location` | `iEventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_location` | `iEventLocationId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_location` | `iReminderCount` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `event_location` | `iStateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_location` | `tBookingComment` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'comment' |
| `event_location_recurring` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_location_recurring` | `dEndTime` | `TIME` | **SKIP** | - | non-text type: TIME |
| `event_location_recurring` | `dEventDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `event_location_recurring` | `dStartTime` | `TIME` | **SKIP** | - | non-text type: TIME |
| `event_location_recurring` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_location_recurring` | `iEventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_location_recurring` | `iEventLocationId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_location_recurring` | `iEventLocationRecId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_location_recurring` | `iTotalHrs` | `TIME` | **SKIP** | - | non-text type: TIME |
| `event_notifications` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_notifications` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_notifications` | `iNotificationId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `global_settings` | `iSettingId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `global_settings` | `vSettingKey` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `google_events` | `dCreatedAt` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `google_events` | `dEventEnd` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `google_events` | `dEventStart` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `google_events` | `dupdatedAt` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `google_events` | `iEventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `google_events` | `iSantaEventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `google_events` | `iSantaId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `google_events` | `iSantaLocationId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `google_events` | `iTalentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `google_events` | `vDescription` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'description' |
| `google_events` | `vEventDescription` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'description' |
| `google_events` | `vGoogleEventId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `google_events` | `vSummary` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'summary' |
| `invoice` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `invoice` | `dInvoiceDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `invoice` | `dInvoiceDueDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `invoice` | `dLastReminderAttempt` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `invoice` | `dRefundDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `invoice` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `invoice` | `fDiscountFee` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice` | `fDiscountPrice` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice` | `fOldPrice` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice` | `fPartialAmt` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice` | `fPendingAmt` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice` | `fPrice` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice` | `fRefundAmount` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice` | `fRequiredPartialAmount` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice` | `fSalesTax` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice` | `fSalesTaxAmount` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice` | `fSalesTotalrefund` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice` | `fShippingPrice` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice` | `fSubTotal` | `DOUBLE` | **SKIP** | - | non-text type: DOUBLE |
| `invoice` | `fTotalPay` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice` | `fTotalRefund` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice` | `iClientId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice` | `iEventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice` | `iEventLocationId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice` | `iInvoiceId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice` | `iReminderRetryCount` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `invoice` | `tClientNotes` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'notes' |
| `invoice` | `vDescription` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'description' |
| `invoice` | `vMailgunId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice` | `vRefundId` | `VARCHAR(225) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_due_date` | `dCreatedDateTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `invoice_due_date` | `dDueDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `invoice_due_date` | `dUpdatedDateTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `invoice_due_date` | `fPrice` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice_due_date` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_due_date` | `iInvoiceId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_payment` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `invoice_payment` | `dRefundDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `invoice_payment` | `dUpdatedDtae` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `invoice_payment` | `fOnlineRefund` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice_payment` | `fSalesTaxAmount` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice_payment` | `fSalesTotalrefund` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice_payment` | `fTotalAmount` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice_payment` | `iInvoiceId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_payment` | `iPaymentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_payment` | `vChargeId` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_payment` | `vRefundId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_payment` | `vTransactionId` | `VARCHAR(225) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_reminder` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `invoice_reminder` | `dDeliveryDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `invoice_reminder` | `dSendDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `invoice_reminder` | `iInvoiceId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_reminder` | `iInvoiceRemId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_save` | `dInvoiceDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `invoice_save` | `dInvoiceDueDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `invoice_save` | `fDiscountFee` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice_save` | `fPartialAmt` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice_save` | `fPendingAmt` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice_save` | `fPrice` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice_save` | `fRefundAmount` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice_save` | `fSalesTax` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice_save` | `fShippingPrice` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice_save` | `iEventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_save` | `iEventLocationId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_save` | `iInvoiceId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_save` | `tClientNotes` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'notes' |
| `last_assigned_santa` | `dAssignedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `last_assigned_santa` | `iAssignedId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `last_assigned_santa` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `log_messages` | `dCreatedDateTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `log_messages` | `dUpdatedTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `log_messages` | `iLogMessageId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `log_messages` | `tLogMessage` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'message' |
| `notifications` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `notifications` | `iNotificationId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `notifications` | `iNotificationType` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `notifications` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `notifications` | `vNotificationMessage` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'message' |
| `payment` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `payment` | `dRefundDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `payment` | `fRefundAmount` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `payment` | `fTotalAmount` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `payment` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `payment` | `iGatewayType` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `payment` | `iPaymentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `payment` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `payment` | `tPaymentResponse` | `MEDIUMTEXT` | **SKIP** | - | free-text name pattern: 'response' |
| `payment` | `vChargeId` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `payment` | `vRefundId` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `payment` | `vTransactionId` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `promo_codes` | `bDeleted` | `TINYINT` | **SKIP** | - | non-text type: TINYINT |
| `promo_codes` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `promo_codes` | `dValidFrom` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `promo_codes` | `dValidTill` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `promo_codes` | `fAmount` | `DECIMAL(8, 2)` | **SKIP** | - | non-text type: DECIMAL(8, 2) |
| `promo_codes` | `iMaximumCount` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `promo_codes` | `iOverallLimit` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `promo_codes` | `iPromoCodeId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `promocode_tracker` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `promocode_tracker` | `fDiscount` | `DECIMAL(8, 2)` | **SKIP** | - | non-text type: DECIMAL(8, 2) |
| `promocode_tracker` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `promocode_tracker` | `iPromoCodeId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `promocode_tracker` | `iTrackerId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `promocode_tracker` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `rating` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `rating` | `fRating` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `rating` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `rating` | `iRatingId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `rating` | `iSantaId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `rating` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `rating` | `vComment` | `VARCHAR(500) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'comment' |
| `rating_reminder` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `rating_reminder` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `rating_reminder` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `rejected_log` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `rejected_log` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `rejected_log` | `iRejectedById` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `rejected_log` | `iRejectedLogId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `reschedule_logs` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `reschedule_logs` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `reschedule_logs` | `iLogId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `retail_affiliates` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `retail_affiliates` | `dDeletedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `retail_affiliates` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `retail_affiliates` | `iCountryId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `retail_affiliates` | `iRetailId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_availability` | `bGuranteedHour` | `TINYINT` | **SKIP** | - | non-text type: TINYINT |
| `santa_availability` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_availability` | `dUTCDateTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_availability` | `dUpdateDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_availability` | `dUserDateTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_availability` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_availability` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_details` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_details` | `iBucketId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_details` | `iTimeZoneId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_details` | `iUserDetailsId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_details` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_emergency_contact` | `dCreatedAt` | `DATE` | **SKIP** | - | non-text type: DATE |
| `santa_emergency_contact` | `dUpdatedAt` | `DATE` | **SKIP** | - | non-text type: DATE |
| `santa_emergency_contact` | `fSantaRate` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `santa_emergency_contact` | `iISantaId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_emergency_contact` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_emergency_contact` | `tSantaNotes` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'notes' |
| `santa_non_availability` | `bGuranteedHour` | `TINYINT` | **SKIP** | - | non-text type: TINYINT |
| `santa_non_availability` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_non_availability` | `dUTCDateTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_non_availability` | `dUpdateDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_non_availability` | `dUserDateTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_non_availability` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_non_availability` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_screening_data` | `dCreatedAt` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_screening_data` | `dUpdatedAt` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_screening_data` | `iScreeningId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_screening_data` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_screening_data` | `tNotes` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'notes' |
| `santa_screening_reminder` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_screening_reminder` | `iReminderId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_screening_reminder` | `iSantaId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santas_finder_details` | `iSantaDetailsId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_email_notifications` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_email_notifications` | `dDeliveryDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_email_notifications` | `dSendDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_email_notifications` | `iReceiverId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_email_notifications` | `iScheduleId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_email_notifications` | `iTemplateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_email_notifications` | `tNotification` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | 501 | average text length 358.7 exceeds 100 |
| `schedule_events` | `createdDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_events` | `eventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_events` | `iEventLocationId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_events` | `scheduleId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_events` | `smsFailMessage` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'message' |
| `schedule_events` | `smsSentDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_events` | `updatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_sms_notifications` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_sms_notifications` | `dDeliveryDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_sms_notifications` | `dSendDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_sms_notifications` | `iNotificationId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_sms_notifications` | `iReceiverId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_sms_notifications` | `iTemplateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_sms_notifications` | `tNotification` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | 501 | average text length 497.3 exceeds 100 |
| `schedule_system_logs` | `dCreatedDateTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_system_logs` | `dUpdatedDateTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_system_logs` | `iAdminId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_system_logs` | `iEventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_system_logs` | `iInvoiceId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_system_logs` | `iLocationId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_system_logs` | `iLogId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_system_logs` | `tLogMessage` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'message' |
| `screening_steps` | `iStepId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `screening_steps` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `sms_templates` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `sms_templates` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `sms_templates` | `iTemplateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `sms_templates` | `tNote` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'note' |
| `sms_templates` | `tSmsContent` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'content' |
| `states` | `iStateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `static_pages` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `static_pages` | `iPageId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `static_pages` | `tPageCode` | `LONGTEXT` | **SKIP** | 2 | average text length 26740.0 exceeds 100 |
| `talent_person_details` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `talent_person_details` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `talent_person_details` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `talent_person_details` | `iStateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `talent_person_details` | `iTalentPersonId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `talent_person_details` | `iTalentTypeId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `talent_person_details` | `tTalentNotes` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'notes' |
| `talent_person_details` | `vTalentHubSpotId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `talent_type` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `talent_type` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `talent_type` | `iTalentTypeId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `unassigned_appointments` | `dAppointmentDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `unassigned_appointments` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `unassigned_appointments` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `user_timezones` | `iCountryId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `user_timezones` | `iTimeZoneId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `users` | `bDeleted` | `TINYINT` | **SKIP** | - | non-text type: TINYINT |
| `users` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `users` | `dHubspotAddDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `users` | `iCountryId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `users` | `iPhnHomeCode` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `users` | `iPhnOfficeCode` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `users` | `iPhnOtherCode` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `users` | `iTimeZoneId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `users` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `users` | `tBio` | `MEDIUMTEXT` | **SKIP** | - | free-text name pattern: 'bio' |
| `users` | `vHubSpotId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |

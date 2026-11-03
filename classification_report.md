# Database Column Classification Report

Deny-first privacy classification summary across all catalog columns.
Values, row data, and credentials are never included in this report.

## Summary Counts

| Class | Column Count | Description |
|---|---|---|
| **BLOCKED** | 103 | Completely excluded from DDL, embeddings, retriever, and logs |
| **MASKED** | 0 | Retained in DDL for queries; output values masked |
| **VALUE_LOW** | 0 | Fully indexed for value resolution (distinct count <= threshold) |
| **VALUE_HIGH** | 0 | Resolved dynamically at query time; not sent to LLM |
| **SKIP** | 773 | Keys, non-text, free text, embeddings, hashes (retained in DDL for joins) |
| **Total** | 876 | Total columns classified |

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
| `event_location` | `eSessionType` | `session` | blocked by name pattern: 'session' |
| `event_location` | `vContactPerson` | `contact` | blocked by name pattern: 'contact' |
| `retail_affiliates` | `vContactNumber` | `contact` | blocked by name pattern: 'contact' |
| `santa_details` | `vDayContactNumber` | `contact` | blocked by name pattern: 'contact' |
| `santa_details` | `vEveningContactNumber` | `contact` | blocked by name pattern: 'contact' |
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
| `admin` | `vContactNumber` | `VARCHAR(20) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'contact' |
| `admin` | `vEmail` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `admin` | `vPassword` | `VARCHAR(200) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'password' |
| `admin` | `vResetToken` | `VARCHAR(10) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `admin_bk(28mar2024)` | `dTokenTime` | `DATETIME` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `admin_bk(28mar2024)` | `iPhoneCode` | `INTEGER` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `admin_bk(28mar2024)` | `vContactNumber` | `VARCHAR(20) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'contact' |
| `admin_bk(28mar2024)` | `vEmail` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `admin_bk(28mar2024)` | `vPassword` | `VARCHAR(200) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'password' |
| `admin_bk(28mar2024)` | `vResetToken` | `VARCHAR(10) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `appointment` | `iPhoneCode` | `INTEGER` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `appointment` | `vAppointmentToken` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `appointment` | `vContactNumber` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'contact' |
| `appointment` | `vEmail` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `appointment` | `vSessionId` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'session' |
| `appointment_parties` | `iPhoneCode` | `INTEGER` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `appointment_parties` | `vEmail` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `appointment_parties` | `vPhoneNo` | `VARCHAR(20) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `assign_talent` | `eEmailStatus` | `VARCHAR(32) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `assign_talent` | `eTalentEmailStatus` | `VARCHAR(32) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `assign_talent` | `tAddress` | `TEXT COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'address' |
| `auto_register_santa_schedule` | `dEmailSentDate` | `DATETIME` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `auto_register_santa_schedule` | `eEmailStatus` | `ENUM` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `auto_register_santa_schedule` | `vEmailFailMessage` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `calendar_auth_detail` | `vAccessToken` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `calendar_auth_detail` | `vNextSyncToken` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `calendar_auth_detail` | `vRefreshToken` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `children` | `dChildBirthDate` | `DATE` | **BLOCKED** | - | blocked by name pattern: 'birth' |
| `client` | `eEmailListed` | `ENUM` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `client` | `eMobileListed` | `ENUM` | **BLOCKED** | - | blocked by name pattern: 'mobile' |
| `client` | `iMobileCode` | `INTEGER` | **BLOCKED** | - | blocked by name pattern: 'mobile' |
| `client` | `tAddress` | `TEXT COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'address' |
| `client` | `vEmail` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `client` | `vMobile` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'mobile' |
| `client` | `vMobileExt` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'mobile' |
| `client` | `vPhoneHome` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `client` | `vPhoneOffice` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `client` | `vPhoneOther` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `countries` | `phoneCode` | `INTEGER` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `email_logs` | `tEmailBody` | `TEXT COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `email_logs` | `vEmailCc` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `email_logs` | `vEmailFrom` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `email_logs` | `vEmailTo` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `email_templates` | `vEmailSubject` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `email_templates_2026(bk)` | `vEmailSubject` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `email_templates_bk2025` | `vEmailSubject` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `email_templates_prev` | `vEmailSubject` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `event_assign_schedule` | `dEmailSentDate` | `DATETIME` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `event_assign_schedule` | `dLastEmailAttempt` | `DATETIME` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `event_assign_schedule` | `eEmailStatus` | `VARCHAR(32) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `event_assign_schedule` | `iEmailRetryCount` | `TINYINT` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `event_assign_schedule` | `vEmailFailMessage` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `event_details` | `locationAddress` | `TEXT COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'address' |
| `event_location` | `eSessionType` | `ENUM` | **BLOCKED** | - | blocked by name pattern: 'session' |
| `event_location` | `tAddress` | `TEXT COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'address' |
| `event_location` | `vAltEmail` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `event_location` | `vAltPhoneNumber` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `event_location` | `vContactPerson` | `VARCHAR(120) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'contact' |
| `event_location` | `vEmail` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `event_location` | `vPhoneNumber` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `event_notifications` | `eEmail` | `ENUM` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `invoice` | `dOtpCreatedAt` | `DATETIME` | **BLOCKED** | - | blocked by name pattern: 'otp' |
| `invoice` | `dReminderEmailSentDate` | `DATE` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `invoice` | `eEmailStatus` | `VARCHAR(32) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `invoice` | `vOtp` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'otp' |
| `retail_affiliates` | `iPhoneCode` | `INTEGER` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `retail_affiliates` | `vContactNumber` | `VARCHAR(20) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'contact' |
| `retail_affiliates` | `vEmail` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `santa_details` | `vDayContactNumber` | `VARCHAR(20) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'contact' |
| `santa_details` | `vEveningContactNumber` | `VARCHAR(20) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'contact' |
| `santa_emergency_contact` | `vSantaAddress` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'address' |
| `santa_emergency_contact` | `vSantaEmail` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `santa_emergency_contact` | `vSantaPhone` | `INTEGER` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `santas_finder_details` | `ContactId` | `INTEGER` | **BLOCKED** | - | blocked by name pattern: 'contact' |
| `santas_finder_details` | `Email` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `santas_finder_details` | `PhoneNumber` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `schedule_events` | `emailFailMessage` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `schedule_events` | `emailSentDate` | `DATETIME` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `schedule_events` | `emailStatus` | `ENUM` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `schedule_events` | `santaEmail` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `schedule_events` | `santaPhoneNumber` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `talent_person_details` | `iMobileCode` | `INTEGER` | **BLOCKED** | - | blocked by name pattern: 'mobile' |
| `talent_person_details` | `tAddress` | `TEXT COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'address' |
| `talent_person_details` | `vEmail` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `talent_person_details` | `vMobile` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'mobile' |
| `users` | `dDob` | `DATETIME` | **BLOCKED** | - | blocked by name pattern: 'dob' |
| `users` | `dTokenTime` | `DATETIME` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `users` | `eEmailListed` | `ENUM` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `users` | `eMobileListed` | `ENUM` | **BLOCKED** | - | blocked by name pattern: 'mobile' |
| `users` | `iPhoneCode` | `INTEGER` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `users` | `tAddress` | `MEDIUMTEXT` | **BLOCKED** | - | blocked by name pattern: 'address' |
| `users` | `vAccessToken` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `users` | `vActivationToken` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `users` | `vContactNumber` | `VARCHAR(15) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'contact' |
| `users` | `vEmail` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'email' |
| `users` | `vPassword` | `VARCHAR(200) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'password' |
| `users` | `vPhoneHome` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `users` | `vPhoneOffice` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `users` | `vPhoneOther` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'phone' |
| `users` | `vResetToken` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'token' |
| `users` | `vSeasonAddress` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **BLOCKED** | - | blocked by name pattern: 'address' |
| `abandoned_mail_sent` | `dCreatedDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `abandoned_mail_sent` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `abandoned_mail_sent` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `abandoned_mail_sent` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `access_permission` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `access_permission` | `eViewType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `access_permission` | `iAccessId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `access_permission` | `iChild` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `access_permission` | `iMenu` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `access_permission` | `iOrderId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `access_permission` | `iParentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `access_permission` | `tIconName` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'TEXT COLLATE utf8mb4_unicode_ci', count unavailable) |
| `access_permission` | `vModuleName` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(125) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `access_permission` | `vUrl` | `VARCHAR(120) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(120) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `access_permission_bk(01apr2024)` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `access_permission_bk(01apr2024)` | `iAccessId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `access_permission_bk(01apr2024)` | `iChild` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `access_permission_bk(01apr2024)` | `iMenu` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `access_permission_bk(01apr2024)` | `iOrderId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `access_permission_bk(01apr2024)` | `iParentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `access_permission_bk(01apr2024)` | `tIconName` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'TEXT COLLATE utf8mb4_unicode_ci', count unavailable) |
| `access_permission_bk(01apr2024)` | `vModuleName` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(125) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `access_permission_bk(01apr2024)` | `vUrl` | `VARCHAR(120) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(120) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `admin` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `admin` | `eDeleteEventStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `admin` | `eUserType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `admin` | `eVerified` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `admin` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `admin` | `vFirstName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `admin` | `vLastName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `admin` | `vProfilePic` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `admin_bk(28mar2024)` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `admin_bk(28mar2024)` | `eUserType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `admin_bk(28mar2024)` | `eVerified` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `admin_bk(28mar2024)` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `admin_bk(28mar2024)` | `vFirstName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `admin_bk(28mar2024)` | `vLastName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `admin_bk(28mar2024)` | `vProfilePic` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `affiliate_codes` | `bDeleted` | `TINYINT` | **SKIP** | - | non-text type: TINYINT |
| `affiliate_codes` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `affiliate_codes` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `affiliate_codes` | `dValidFrom` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `affiliate_codes` | `dValidTill` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `affiliate_codes` | `eAffiliateType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `affiliate_codes` | `eCommissionType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `affiliate_codes` | `eDiscountType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `affiliate_codes` | `eStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `affiliate_codes` | `fAmount` | `DECIMAL(8, 2)` | **SKIP** | - | non-text type: DECIMAL(8, 2) |
| `affiliate_codes` | `fCommissionFee` | `DECIMAL(8, 2)` | **SKIP** | - | non-text type: DECIMAL(8, 2) |
| `affiliate_codes` | `fLiveCallPrice` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `affiliate_codes` | `fPreRecodeVideoPrice` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `affiliate_codes` | `iAffiliateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `affiliate_codes` | `iClicks` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `affiliate_codes` | `iConverted` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `affiliate_codes` | `iSantaId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `affiliate_codes` | `vAffiliateCode` | `VARCHAR(20) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(20) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `affiliate_codes` | `vAffiliateLink` | `VARCHAR(500) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(500) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `affiliate_codes` | `vAffiliateName` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
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
| `appointment` | `eAppointmentStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `appointment` | `eAppointmentType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `appointment` | `eCanReschedule` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `appointment` | `eChildReminderStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `appointment` | `eFileStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `appointment` | `eLinkMailSend` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `appointment` | `eRescheduleByAdmin` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `appointment` | `fAppointmentFee` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `appointment` | `fDiscountFee` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `appointment` | `fTax` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `appointment` | `iAffiliateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment` | `iAppointmentNum` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(50) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `appointment` | `iCountryId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment` | `iOldSantaId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment` | `iPin` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `appointment` | `iPromoCodeId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment` | `iSantaId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment` | `isDefferentExitVideo` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `appointment` | `isReminded` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `appointment` | `isSantaReminded` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `appointment` | `timezone` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `appointment` | `vArchiveId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment` | `vEncodedFIle` | `VARCHAR(500) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(500) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `appointment` | `vFirstName` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `appointment` | `vLastName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `appointment` | `vPreferredLanguage` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `appointment` | `vRecordedFIle` | `VARCHAR(500) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(500) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `appointment` | `vRejected_By` | `VARCHAR(30) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(30) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `appointment` | `vThumbnail` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `appointment` | `vTokboxId` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment_parties` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `appointment_parties` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment_parties` | `iCountryId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment_parties` | `iPartyId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment_parties` | `iPin` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `appointment_parties` | `iTimeZoneId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `appointment_parties` | `vPartyName` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `appointment_parties` | `vPartyNo` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(50) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `appointment_parties` | `vRelationship` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
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
| `assign_talent` | `eBilingType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `assign_talent` | `eNewStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `assign_talent` | `eRecurring` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `assign_talent` | `eStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `assign_talent` | `eTalentFeeType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `assign_talent` | `eTalentPaid` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `assign_talent` | `eTalentStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `assign_talent` | `eTalentStopReminder` | `ENUM` | **SKIP** | - | non-text type: ENUM |
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
| `assign_talent` | `tTalentRequirements` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'TEXT COLLATE utf8mb4_unicode_ci', count unavailable) |
| `assign_talent` | `vMailgunId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `assign_talent` | `vTalentMailgunId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `auto_register_santa_schedule` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `auto_register_santa_schedule` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `auto_register_santa_schedule` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `auto_register_santa_schedule` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `auto_register_santa_schedule` | `vData` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
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
| `buckets` | `vBucketName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `calendar_auth_detail` | `dCalendarWatch` | `DATE` | **SKIP** | - | non-text type: DATE |
| `calendar_auth_detail` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `calendar_auth_detail` | `dUpdatedDtae` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `calendar_auth_detail` | `eCalStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `calendar_auth_detail` | `eHsssStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `calendar_auth_detail` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `calendar_auth_detail` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `calendar_auth_detail` | `vCalendarId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `calendar_auth_detail` | `vResourceId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `calendar_auth_detail` | `vResourceUri` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `calendar_auth_detail` | `vUUID` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `call_event_logs` | `dEventCreateAt` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `call_event_logs` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `call_event_logs` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `call_event_logs` | `tEventMsg` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'TEXT COLLATE utf8mb4_unicode_ci', count unavailable) |
| `call_event_logs` | `vEvent` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `call_logs` | `dBufferStartTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `call_logs` | `dCallStartTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `call_logs` | `dSantaJoined` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `call_logs` | `dUserJoined` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `call_logs` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `call_logs` | `ilogId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `children` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `children` | `eGender` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `children` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `children` | `iChildId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `children` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `children` | `tOtherNotes` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'notes' |
| `children` | `vAccomplishments` | `VARCHAR(500) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(500) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `children` | `vChildLocation` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `children` | `vChildName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `children` | `vChildNamePronunciation` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `children` | `vEncouragementToImprove` | `VARCHAR(500) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(500) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `children` | `vGifts` | `VARCHAR(500) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(500) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `children` | `vGrade` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `children` | `vPetsInfo` | `VARCHAR(500) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(500) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `children` | `vSchool` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `children` | `vTeacherName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `client` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `client` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `client` | `ePhnHomeListed` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `client` | `ePhnOffcListed` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `client` | `ePhnOtherListed` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `client` | `eStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `client` | `eTitle` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `client` | `eWebListed` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `client` | `iClientId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `client` | `iPhnHomeCode` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `client` | `iPhnOfficeCode` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `client` | `iPhnOtherCode` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `client` | `iStateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `client` | `vCity` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `client` | `vClientHubSpotId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `client` | `vCompanyName` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(125) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `client` | `vFirstName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `client` | `vLastName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `client` | `vMidName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `client` | `vNickName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `client` | `vPhnHomeExt` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `client` | `vPhnOffcExt` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `client` | `vPhnOtherExt` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `client` | `vWebsite` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(125) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `client` | `vZipCode` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `countries` | `country_name` | `VARCHAR(150) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(150) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `countries` | `id` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `countries` | `sortname` | `VARCHAR(3) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(3) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `day_pricing` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `day_pricing` | `dDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `day_pricing` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `day_pricing` | `fPCPrice` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `day_pricing` | `fVCPrice` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `day_pricing` | `iDayPriceId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `email_logs` | `dCreatedAt` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `email_logs` | `dUpdatedAt` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `email_logs` | `eDeleteStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `email_logs` | `eMailStatus` | `VARCHAR(32) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(32) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `email_logs` | `iEventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `email_logs` | `iLogId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `email_logs` | `vMailgunMessageId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `email_logs` | `vPurpose` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `email_logs` | `vRecipient` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `email_logs` | `vSubject` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `email_templates` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `email_templates` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `email_templates` | `eStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `email_templates` | `eTemplateFor` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `email_templates` | `iTemplateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `email_templates` | `tNote` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'note' |
| `email_templates` | `tTemplateContent` | `LONGTEXT` | **SKIP** | - | free-text name pattern: 'content' |
| `email_templates` | `vTemplateName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `email_templates_2026(bk)` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `email_templates_2026(bk)` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `email_templates_2026(bk)` | `eStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `email_templates_2026(bk)` | `eTemplateFor` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `email_templates_2026(bk)` | `iTemplateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `email_templates_2026(bk)` | `tNote` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'note' |
| `email_templates_2026(bk)` | `tTemplateContent` | `LONGTEXT` | **SKIP** | - | free-text name pattern: 'content' |
| `email_templates_2026(bk)` | `vTemplateName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `email_templates_bk2025` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `email_templates_bk2025` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `email_templates_bk2025` | `eStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `email_templates_bk2025` | `eTemplateFor` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `email_templates_bk2025` | `iTemplateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `email_templates_bk2025` | `tNote` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'note' |
| `email_templates_bk2025` | `tTemplateContent` | `LONGTEXT` | **SKIP** | - | free-text name pattern: 'content' |
| `email_templates_bk2025` | `vTemplateName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `email_templates_prev` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `email_templates_prev` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `email_templates_prev` | `eStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `email_templates_prev` | `eTemplateFor` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `email_templates_prev` | `iTemplateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `email_templates_prev` | `tNote` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'note' |
| `email_templates_prev` | `tTemplateContent` | `LONGTEXT` | **SKIP** | - | free-text name pattern: 'content' |
| `email_templates_prev` | `vTemplateName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `event` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event` | `dFollowUpReminder` | `DATE` | **SKIP** | - | non-text type: DATE |
| `event` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event` | `eEventStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `event` | `eStopReminder` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `event` | `fDiscountFee` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `event` | `fEventFee` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `event` | `fShippingFee` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `event` | `fTax` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `event` | `iClientId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event` | `iEventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event` | `tBookingComment` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'comment' |
| `event` | `tCancelReason` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'TEXT COLLATE utf8mb4_unicode_ci', count unavailable) |
| `event` | `tPerfomerComment` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'comment' |
| `event` | `vEventName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `event_assign_schedule` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_assign_schedule` | `dSmsSentDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_assign_schedule` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_assign_schedule` | `eAssignType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `event_assign_schedule` | `eSmsStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `event_assign_schedule` | `eTalentType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `event_assign_schedule` | `iEventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_assign_schedule` | `iEventLocationId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_assign_schedule` | `iSantaId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_assign_schedule` | `iScheduleIdId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_assign_schedule` | `iTalentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_assign_schedule` | `vMailgunId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_assign_schedule` | `vSmsFailMessage` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'message' |
| `event_details` | `assignednotes` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'TEXT COLLATE utf8mb4_unicode_ci', count unavailable) |
| `event_details` | `beginTime` | `VARCHAR(10) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(10) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `event_details` | `createdDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_details` | `endTime` | `VARCHAR(10) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(10) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `event_details` | `eventDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `event_details` | `eventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_details` | `eventName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `event_details` | `latitude` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `event_details` | `locationCity` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `event_details` | `locationState` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `event_details` | `locationZip` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `event_details` | `longitude` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `event_details` | `notes` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'notes' |
| `event_details` | `payRate` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `event_details` | `updatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_location` | `dAssignTalentMailSentDatetime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_location` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_location` | `dEndTime` | `TIME` | **SKIP** | - | non-text type: TIME |
| `event_location` | `dEventDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `event_location` | `dLastReminderDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `event_location` | `dRepeatUntilDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `event_location` | `dStartTime` | `TIME` | **SKIP** | - | non-text type: TIME |
| `event_location` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_location` | `eBookingStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `event_location` | `eSameLocation` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `event_location` | `eStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `event_location` | `eTalentStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `event_location` | `iAltCountryCode` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `event_location` | `iCountryCode` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `event_location` | `iEventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_location` | `iEventLocationId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_location` | `iReminderCount` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `event_location` | `iStateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_location` | `iTotalHrs` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(125) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `event_location` | `tBookingComment` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'comment' |
| `event_location` | `tCancelBookingReason` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'TEXT COLLATE utf8mb4_unicode_ci', count unavailable) |
| `event_location` | `vCity` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `event_location` | `vLatitude` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `event_location` | `vLongitude` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `event_location` | `vSelectedDays` | `VARCHAR(225) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(225) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `event_location` | `vZipCode` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `event_location_recurring` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_location_recurring` | `dEndTime` | `TIME` | **SKIP** | - | non-text type: TIME |
| `event_location_recurring` | `dEventDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `event_location_recurring` | `dStartTime` | `TIME` | **SKIP** | - | non-text type: TIME |
| `event_location_recurring` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_location_recurring` | `iEventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_location_recurring` | `iEventLocationId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_location_recurring` | `iEventLocationRecId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_location_recurring` | `iTotalHrs` | `TIME` | **SKIP** | - | non-text type: TIME |
| `event_location_recurring` | `vDay` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `event_notifications` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_notifications` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `event_notifications` | `eAdmin` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `event_notifications` | `eSMS` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `event_notifications` | `eSanta` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `event_notifications` | `eUser` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `event_notifications` | `iNotificationId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `event_notifications` | `vNotificationName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `global_settings` | `eIsVisible` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `global_settings` | `iSettingId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `global_settings` | `vSettingKey` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `global_settings` | `vSettingValue` | `VARCHAR(2000) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(2000) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `google_events` | `dCreatedAt` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `google_events` | `dEventEnd` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `google_events` | `dEventStart` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `google_events` | `dupdatedAt` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `google_events` | `eEventType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `google_events` | `iEventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `google_events` | `iSantaEventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `google_events` | `iSantaId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `google_events` | `iSantaLocationId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `google_events` | `iTalentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `google_events` | `vDescription` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'description' |
| `google_events` | `vEventDescription` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'description' |
| `google_events` | `vEventLocation` | `VARCHAR(225) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(225) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `google_events` | `vGoogleEventId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `google_events` | `vStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `google_events` | `vSummary` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'summary' |
| `google_events` | `vTimeZone` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `invoice` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `invoice` | `dInvoiceDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `invoice` | `dInvoiceDueDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `invoice` | `dLastReminderAttempt` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `invoice` | `dRefundDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `invoice` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `invoice` | `eBilingType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice` | `eDiscountType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice` | `eInvoiceFor` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice` | `eInvoiceGenerateType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice` | `eInvoiceStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice` | `eInvoiceType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice` | `eNoSalesTax` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice` | `eOldInvoiceStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice` | `eRequiredAmountType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice` | `eRequiredType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
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
| `invoice` | `vInvoiceNo` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(125) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `invoice` | `vMailgunId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice` | `vPurchaseOrder` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `invoice` | `vRefundId` | `VARCHAR(225) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_due_date` | `dCreatedDateTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `invoice_due_date` | `dDueDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `invoice_due_date` | `dUpdatedDateTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `invoice_due_date` | `eCreatedType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice_due_date` | `eHideBox` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice_due_date` | `ePaidStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice_due_date` | `fPrice` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice_due_date` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_due_date` | `iInvoiceId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_payment` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `invoice_payment` | `dRefundDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `invoice_payment` | `dUpdatedDtae` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `invoice_payment` | `ePaymentMode` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice_payment` | `eRefundMode` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice_payment` | `eRefunded` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice_payment` | `eType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice_payment` | `fOnlineRefund` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice_payment` | `fSalesTaxAmount` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice_payment` | `fSalesTotalrefund` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice_payment` | `fTotalAmount` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `invoice_payment` | `iInvoiceId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_payment` | `iPaymentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_payment` | `is_fully_refunded` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice_payment` | `vChargeId` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_payment` | `vChequeNumber` | `VARCHAR(225) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(225) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `invoice_payment` | `vPaymentStatus` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `invoice_payment` | `vRefundAmount` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `invoice_payment` | `vRefundChequeNumber` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `invoice_payment` | `vRefundId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_payment` | `vTransactionId` | `VARCHAR(225) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_reminder` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `invoice_reminder` | `dDeliveryDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `invoice_reminder` | `dSendDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `invoice_reminder` | `eStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice_reminder` | `iInvoiceId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_reminder` | `iInvoiceRemId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `invoice_save` | `dInvoiceDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `invoice_save` | `dInvoiceDueDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `invoice_save` | `eBilingType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice_save` | `eDiscountType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice_save` | `eInvoiceFor` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice_save` | `eInvoiceStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `invoice_save` | `eInvoiceType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
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
| `invoice_save` | `vInvoiceNo` | `VARCHAR(125) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(125) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `last_assigned_santa` | `dAssignedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `last_assigned_santa` | `iAssignedId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `last_assigned_santa` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `log_messages` | `dCreatedDateTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `log_messages` | `dUpdatedTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `log_messages` | `eLogType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `log_messages` | `iLogMessageId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `log_messages` | `tLogMessage` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'message' |
| `notifications` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `notifications` | `eIsRead` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `notifications` | `iNotificationId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `notifications` | `iNotificationType` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `notifications` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `notifications` | `vNotificationMessage` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'message' |
| `payment` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `payment` | `dRefundDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `payment` | `eRefundBy` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `payment` | `fRefundAmount` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `payment` | `fTotalAmount` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `payment` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `payment` | `iGatewayType` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `payment` | `iPaymentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `payment` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `payment` | `tPaymentResponse` | `MEDIUMTEXT` | **SKIP** | - | free-text name pattern: 'response' |
| `payment` | `vChargeId` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `payment` | `vCurrency` | `VARCHAR(10) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(10) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `payment` | `vPaymentStatus` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `payment` | `vRefundId` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `payment` | `vRefundStatus` | `VARCHAR(70) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(70) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `payment` | `vTransactionId` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `promo_codes` | `bDeleted` | `TINYINT` | **SKIP** | - | non-text type: TINYINT |
| `promo_codes` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `promo_codes` | `dValidFrom` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `promo_codes` | `dValidTill` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `promo_codes` | `eDiscountType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `promo_codes` | `ePromoCodeType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `promo_codes` | `eStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `promo_codes` | `fAmount` | `DECIMAL(8, 2)` | **SKIP** | - | non-text type: DECIMAL(8, 2) |
| `promo_codes` | `iMaximumCount` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `promo_codes` | `iOverallLimit` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `promo_codes` | `iPromoCodeId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `promo_codes` | `vPromoCode` | `VARCHAR(20) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(20) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `promo_codes` | `vPromoName` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `promocode_tracker` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `promocode_tracker` | `ePromocodeUsed` | `ENUM` | **SKIP** | - | non-text type: ENUM |
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
| `rejected_log` | `eRejectedByType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `rejected_log` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `rejected_log` | `iRejectedById` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `rejected_log` | `iRejectedLogId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `reschedule_logs` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `reschedule_logs` | `eAppointmentType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `reschedule_logs` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `reschedule_logs` | `iLogId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `reschedule_logs` | `tAppointmentData` | `TEXT` | **SKIP** | - | unclassifiable column (text type 'TEXT', count unavailable) |
| `retail_affiliates` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `retail_affiliates` | `dDeletedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `retail_affiliates` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `retail_affiliates` | `eStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `retail_affiliates` | `iCountryId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `retail_affiliates` | `iRetailId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `retail_affiliates` | `vCompanyName` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `retail_affiliates` | `vFirstName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `retail_affiliates` | `vLastName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `santa_availability` | `bGuranteedHour` | `TINYINT` | **SKIP** | - | non-text type: TINYINT |
| `santa_availability` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_availability` | `dUTCDateTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_availability` | `dUpdateDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_availability` | `dUserDateTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_availability` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_availability` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_details` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_details` | `eMarkAsPCR` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `santa_details` | `eScreeningStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `santa_details` | `iBucketId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_details` | `iTimeZoneId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_details` | `iUserDetailsId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_details` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_details` | `vEnglishFluency` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `santa_details` | `vExperience` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `santa_details` | `vSpanishFluency` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `santa_emergency_contact` | `dCreatedAt` | `DATE` | **SKIP** | - | non-text type: DATE |
| `santa_emergency_contact` | `dUpdatedAt` | `DATE` | **SKIP** | - | non-text type: DATE |
| `santa_emergency_contact` | `fSantaRate` | `FLOAT` | **SKIP** | - | non-text type: FLOAT |
| `santa_emergency_contact` | `iISantaId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_emergency_contact` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_emergency_contact` | `tSantaNotes` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'notes' |
| `santa_emergency_contact` | `vSantaName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `santa_emergency_contact` | `vSantaRating` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `santa_non_availability` | `bGuranteedHour` | `TINYINT` | **SKIP** | - | non-text type: TINYINT |
| `santa_non_availability` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_non_availability` | `dUTCDateTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_non_availability` | `dUpdateDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_non_availability` | `dUserDateTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_non_availability` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_non_availability` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_screening_data` | `dCreatedAt` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_screening_data` | `dUpdatedAt` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_screening_data` | `eEnglishLanguage` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `santa_screening_data` | `eSantaDress` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `santa_screening_data` | `eSpanishLanguage` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `santa_screening_data` | `eStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `santa_screening_data` | `iBrowserCheck` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `santa_screening_data` | `iCameraCheck` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `santa_screening_data` | `iMicrophoneCheck` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `santa_screening_data` | `iScreeningId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_screening_data` | `iSpeedTest` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `santa_screening_data` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_screening_data` | `tNotes` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'notes' |
| `santa_screening_data` | `tSantaDressAssets` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'TEXT COLLATE utf8mb4_unicode_ci', count unavailable) |
| `santa_screening_data` | `tScreeningVideo` | `MEDIUMTEXT` | **SKIP** | - | unclassifiable column (text type 'MEDIUMTEXT', count unavailable) |
| `santa_screening_data` | `vBrowserName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `santa_screening_data` | `vSpeed` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `santa_screening_reminder` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `santa_screening_reminder` | `iReminderId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santa_screening_reminder` | `iSantaId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santas_finder_details` | `FirstName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `santas_finder_details` | `LastName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `santas_finder_details` | `PostalCode` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `santas_finder_details` | `TimeZone` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `santas_finder_details` | `iSantaDetailsId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `santas_finder_details` | `latitude` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(50) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `santas_finder_details` | `longitude` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(50) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `schedule_email_notifications` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_email_notifications` | `dDeliveryDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_email_notifications` | `dSendDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_email_notifications` | `eReceiverType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `schedule_email_notifications` | `eSendingFrom` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `schedule_email_notifications` | `eStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `schedule_email_notifications` | `iReceiverId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_email_notifications` | `iScheduleId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_email_notifications` | `iTemplateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_email_notifications` | `tNotification` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'TEXT COLLATE utf8mb4_unicode_ci', count unavailable) |
| `schedule_events` | `createdDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_events` | `eTalentType` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `schedule_events` | `eventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_events` | `iEventLocationId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_events` | `santaPostalCode` | `VARCHAR(15) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(15) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `schedule_events` | `santaTimeZone` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(50) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `schedule_events` | `scheduleId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_events` | `smsFailMessage` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'message' |
| `schedule_events` | `smsSentDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_events` | `smsStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `schedule_events` | `snataName` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `schedule_events` | `updatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_sms_notifications` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_sms_notifications` | `dDeliveryDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_sms_notifications` | `dSendDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_sms_notifications` | `eReceiverType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `schedule_sms_notifications` | `eStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `schedule_sms_notifications` | `iNotificationId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_sms_notifications` | `iReceiverId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_sms_notifications` | `iTemplateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_sms_notifications` | `tNotification` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'TEXT COLLATE utf8mb4_unicode_ci', count unavailable) |
| `schedule_system_logs` | `dCreatedDateTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_system_logs` | `dUpdatedDateTime` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `schedule_system_logs` | `iAdminId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_system_logs` | `iEventId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_system_logs` | `iInvoiceId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_system_logs` | `iLocationId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_system_logs` | `iLogId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `schedule_system_logs` | `tLogMessage` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'message' |
| `schedule_system_logs` | `vEventName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `screening_steps` | `eStep` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `screening_steps` | `iStepId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `screening_steps` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `sms_templates` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `sms_templates` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `sms_templates` | `eStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `sms_templates` | `eTemplateFor` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `sms_templates` | `iTemplateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `sms_templates` | `tNote` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'note' |
| `sms_templates` | `tSmsContent` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'content' |
| `states` | `eStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `states` | `iStateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `states` | `vStateCode` | `VARCHAR(100)` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100)', count unavailable) |
| `states` | `vStateName` | `VARCHAR(200)` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(200)', count unavailable) |
| `static_pages` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `static_pages` | `iPageId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `static_pages` | `tPageCode` | `LONGTEXT` | **SKIP** | - | unclassifiable column (text type 'LONGTEXT', count unavailable) |
| `static_pages` | `tPageSlug` | `TEXT COLLATE utf8mb4_unicode_520_ci` | **SKIP** | - | unclassifiable column (text type 'TEXT COLLATE utf8mb4_unicode_520_ci', count unavailable) |
| `static_pages` | `vPageName` | `VARCHAR(100) COLLATE utf8mb3_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb3_unicode_ci', count unavailable) |
| `talent_person_details` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `talent_person_details` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `talent_person_details` | `eAccountType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `talent_person_details` | `eStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `talent_person_details` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `talent_person_details` | `iStateId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `talent_person_details` | `iTalentPersonId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `talent_person_details` | `iTalentTypeId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `talent_person_details` | `latitude` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(50) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `talent_person_details` | `longitude` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(50) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `talent_person_details` | `tTalentNotes` | `TEXT COLLATE utf8mb4_unicode_ci` | **SKIP** | - | free-text name pattern: 'notes' |
| `talent_person_details` | `vAccountNumber` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `talent_person_details` | `vBankName` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `talent_person_details` | `vCity` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `talent_person_details` | `vFirstName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `talent_person_details` | `vLastName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `talent_person_details` | `vOtherPayType` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `talent_person_details` | `vRoutingNumber` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `talent_person_details` | `vTalentHubSpotId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `talent_person_details` | `vZipcode` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `talent_type` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `talent_type` | `dUpdatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `talent_type` | `eStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `talent_type` | `iTalentTypeId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `talent_type` | `vTalentType` | `VARCHAR(120) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(120) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `unassigned_appointments` | `dAppointmentDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `unassigned_appointments` | `iAppointmentId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `unassigned_appointments` | `iId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `user_timezones` | `iCountryId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `user_timezones` | `iTimeZoneId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `user_timezones` | `vTimeZone` | `VARCHAR(11) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(11) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `user_timezones` | `vTimeZoneAbv` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `user_timezones` | `vTimeZoneDST` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(50) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `user_timezones` | `vTimeZoneName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `bDeleted` | `TINYINT` | **SKIP** | - | non-text type: TINYINT |
| `users` | `dCreatedDate` | `DATETIME` | **SKIP** | - | non-text type: DATETIME |
| `users` | `dHubspotAddDate` | `DATE` | **SKIP** | - | non-text type: DATE |
| `users` | `eAccountType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `users` | `eAuditionStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `users` | `eGender` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `users` | `eIsGoogleCalendar` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `users` | `ePhnHomeListed` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `users` | `ePhnOffcListed` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `users` | `ePhnOtherListed` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `users` | `eRegisterType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `users` | `eStatus` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `users` | `eUserType` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `users` | `eVerified` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `users` | `eWebListed` | `ENUM` | **SKIP** | - | non-text type: ENUM |
| `users` | `iCountryId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `users` | `iPhnHomeCode` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `users` | `iPhnOfficeCode` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `users` | `iPhnOtherCode` | `INTEGER` | **SKIP** | - | non-text type: INTEGER |
| `users` | `iSeasonState` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `iTimeZoneId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `users` | `iUserId` | `INTEGER` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `users` | `iZipCode` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(50) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `isAffiliated` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `latitude` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(50) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `longitude` | `VARCHAR(50) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(50) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `tBio` | `MEDIUMTEXT` | **SKIP** | - | free-text name pattern: 'bio' |
| `users` | `vAccountNumber` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `vAffiliateCode` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `vAltUserMail` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `vBankName` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `vCity` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `vFirstName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `vHubSpotId` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | key or identifier column (available in DDL for joins) |
| `users` | `vLastName` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `vOtherPayType` | `VARCHAR(255) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(255) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `vPhnHomeExt` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `vPhnOffcExt` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `vPhnOtherExt` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `vProfilePic` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `vRoutingNumber` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `vSeasonCity` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `vSeasonZip` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `vState` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |
| `users` | `vWebsite` | `VARCHAR(100) COLLATE utf8mb4_unicode_ci` | **SKIP** | - | unclassifiable column (text type 'VARCHAR(100) COLLATE utf8mb4_unicode_ci', count unavailable) |

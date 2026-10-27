CREATE TABLE `ai_runs` (
	`id` text PRIMARY KEY NOT NULL,
	`owner` text NOT NULL,
	`property_id` text NOT NULL,
	`assessment_id` text NOT NULL,
	`hash` text NOT NULL,
	`month` text NOT NULL,
	`status` text NOT NULL,
	`reserved_micros` integer NOT NULL,
	`actual_micros` integer,
	`created_at` text NOT NULL,
	`result` text
);
--> statement-breakpoint
CREATE UNIQUE INDEX `one_run_per_input` ON `ai_runs` (`assessment_id`,`hash`);--> statement-breakpoint
CREATE INDEX `monthly_usage` ON `ai_runs` (`month`);--> statement-breakpoint
CREATE TABLE `assessments` (
	`id` text PRIMARY KEY NOT NULL,
	`property_id` text NOT NULL,
	`owner` text NOT NULL,
	`version` integer NOT NULL,
	`revision` integer DEFAULT 0 NOT NULL,
	`data` text NOT NULL,
	FOREIGN KEY (`property_id`) REFERENCES `properties`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `assessment_version` ON `assessments` (`property_id`,`version`);--> statement-breakpoint
CREATE INDEX `assessment_owner` ON `assessments` (`owner`);--> statement-breakpoint
CREATE TABLE `budgets` (
	`month` text PRIMARY KEY NOT NULL,
	`used_micros` integer DEFAULT 0 NOT NULL
);
--> statement-breakpoint
CREATE TABLE `properties` (
	`id` text PRIMARY KEY NOT NULL,
	`owner` text NOT NULL,
	`data` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `one_property_per_owner` ON `properties` (`owner`);
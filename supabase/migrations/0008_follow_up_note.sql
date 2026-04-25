-- Add follow_up_note to contacts so nudge messages can reference
-- the reason a follow-up was scheduled.
ALTER TABLE contacts ADD COLUMN follow_up_note text;

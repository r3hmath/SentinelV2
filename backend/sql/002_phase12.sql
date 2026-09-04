ALTER TABLE public.events
ADD COLUMN IF NOT EXISTS processing_status VARCHAR(30)
    NOT NULL DEFAULT 'processed';

ALTER TABLE public.events
ADD COLUMN IF NOT EXISTS processing_attempts INTEGER
    NOT NULL DEFAULT 0;

ALTER TABLE public.events
ADD COLUMN IF NOT EXISTS last_processing_error TEXT;

ALTER TABLE public.events
ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_events_processing_status
ON public.events(processing_status);
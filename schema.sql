
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL,
    pwhash TEXT NOT NULL
);

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO omenusr;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO omenusr;

CREATE TABLE public.datasets
(
    id text COLLATE pg_catalog."default" NOT NULL,
    owner integer NOT NULL,
    metadata jsonb NOT NULL,
    content text COLLATE pg_catalog."default",
    CONSTRAINT datasets_pkey PRIMARY KEY (id, owner)
)
WITH (
    OIDS = FALSE
)
TABLESPACE pg_default;

ALTER TABLE public.datasets
    OWNER to omenusr;
    
CREATE TABLE public.annotations
(
    uid integer NOT NULL,
    dataset text NOT NULL,
    sample text NOT NULL,
    annotation text NOT NULL,
    PRIMARY KEY (uid, dataset, sample)
)
WITH (
    OIDS = FALSE
)
TABLESPACE pg_default;

ALTER TABLE public.annotations
    OWNER to omenusr;

CREATE TABLE IF NOT EXISTS interpret_result (
    template_name varchar(64) NOT NULL,
    as_of date NOT NULL,
    request_model varchar(64) NOT NULL,
    response_model varchar(64) NOT NULL,
    content text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (template_name, as_of, request_model)
);

CREATE TABLE tracked_topics (
    project                 text NOT NULL,   -- 'en.wikipedia' | 'ja.wikipedia' | 'ko.wikipedia' | 'pt.wikipedia'
    article                 text NOT NULL,   -- exact Wikipedia article title
    topic_label             text NOT NULL,
    added_at                timestamptz NOT NULL DEFAULT now(),
    added_by_opportunity_id bigint,          -- FK added in 0005_opportunities.sql, once that table exists
    PRIMARY KEY (project, article)
);

CREATE TABLE wikipedia_pageviews_daily (
    project       text NOT NULL,
    article       text NOT NULL,
    pageview_date date NOT NULL,
    views         bigint NOT NULL,
    fetched_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project, article, pageview_date)
);
CREATE INDEX ix_wikipedia_pageviews_article_date ON wikipedia_pageviews_daily (article, pageview_date);

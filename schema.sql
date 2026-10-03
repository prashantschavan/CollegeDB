-- My Saver : Supabase schema (multi-user)
-- Run once in Supabase Dashboard -> SQL Editor -> New query -> paste -> Run.

create extension if not exists pgcrypto;

-- 0) Accounts (passwords are scrypt-hashed by the server)
create table if not exists users (
    id             uuid primary key default gen_random_uuid(),
    email          text unique not null,
    name           text not null,
    password_hash  text not null,
    created_at     timestamptz not null default now()
);

-- 1) Raw record of every share (nothing is lost, even if reading fails)
create table if not exists messages (
    id            uuid primary key default gen_random_uuid(),
    user_id       uuid not null references users(id) on delete cascade,
    client_id     text not null,                -- generated on the phone; stops double-saves on retry
    content_kind  text not null,                -- text | link | youtube | image | pdf | document | audio | video
    shared_title  text,
    text_content  text,                         -- shared text / caption / link
    urls          text[] default '{}',
    media_path    text,                         -- path inside the storage bucket
    media_mime    text,
    filename      text,
    size_bytes    bigint,
    status        text not null default 'processing',   -- processing | processed | stored | failed
    error         text,
    received_at   timestamptz not null default now(),
    unique (user_id, client_id)
);
create index if not exists messages_user_idx     on messages (user_id, received_at desc);
create index if not exists messages_status_idx   on messages (status);
create index if not exists messages_received_idx on messages (received_at desc);

-- 2) Structured information extracted by Gemini
create table if not exists items (
    id                 uuid primary key default gen_random_uuid(),
    message_id         uuid not null references messages(id) on delete cascade,
    category           text,
    title              text,
    summary            text,
    issuing_authority  text,
    reference_no       text,
    issue_date         date,
    deadline           date,
    key_dates          jsonb default '[]',      -- [{label, date, time}]
    action_items       jsonb default '[]',
    people             text[] default '{}',
    departments        text[] default '{}',
    tags               text[] default '{}',
    language           text,
    confidence         real,
    source_url         text,
    source_meta        jsonb default '{}',      -- youtube channel/duration, page title, file name...
    created_at         timestamptz not null default now(),
    search             tsvector
);
create index if not exists items_message_idx  on items (message_id);
create index if not exists items_category_idx on items (category);
create index if not exists items_deadline_idx on items (deadline);
create index if not exists items_tags_idx     on items using gin (tags);
create index if not exists items_search_idx   on items using gin (search);
create index if not exists items_created_idx  on items (created_at desc);

-- Keep the full-text search column up to date (title and tags weigh most)
create or replace function items_search_update() returns trigger language plpgsql as $$
begin
  new.search :=
      setweight(to_tsvector('english', coalesce(new.title, '')), 'A')
   || setweight(to_tsvector('english', coalesce(array_to_string(new.tags, ' '), '')), 'A')
   || setweight(to_tsvector('english',
        coalesce(new.summary, '') || ' ' || coalesce(new.issuing_authority, '') || ' ' ||
        coalesce(new.reference_no, '') || ' ' || coalesce(array_to_string(new.people, ' '), '') || ' ' ||
        coalesce(array_to_string(new.departments, ' '), '')), 'B');
  return new;
end $$;
drop trigger if exists items_search_trg on items;
create trigger items_search_trg before insert or update on items
  for each row execute function items_search_update();

-- Items joined with their original share
create or replace view items_full with (security_invoker = true) as
select i.*, m.user_id, m.content_kind, m.text_content, m.urls, m.media_path, m.media_mime, m.filename, m.received_at
from items i join messages m on m.id = i.message_id;

-- Search used by the app: keyword (stemmed) + partial-word match, category filter, upcoming deadlines
drop function if exists search_items(uuid, text, text, boolean, int);
create or replace function search_items(uid uuid, q text default null, cat text default null,
                                        upcoming boolean default false, lim int default 50)
returns setof items_full language sql stable as $$
  select * from items_full
  where user_id = uid
    and (q is null or q = ''
         or search @@ websearch_to_tsquery('english', q)
         or title ilike '%' || q || '%'
         or summary ilike '%' || q || '%'
         or array_to_string(tags, ' ') ilike '%' || q || '%')
    and (cat is null or cat = '' or category = cat)
    and (not upcoming or deadline >= (now() at time zone 'Asia/Kolkata')::date)
  order by case when upcoming then deadline end asc nulls last, created_at desc
  limit lim;
$$;

-- Lock down: only the server (service_role key) may touch data
alter table users    enable row level security;
alter table messages enable row level security;
alter table items    enable row level security;
revoke execute on function search_items(uuid, text, text, boolean, int) from public, anon, authenticated;

-- 3) Private bucket for original images / PDFs / audio / video
insert into storage.buckets (id, name, public)
values ('wa-media', 'wa-media', false)
on conflict (id) do nothing;

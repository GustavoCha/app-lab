create extension if not exists pgcrypto;

create table if not exists public.users (
    id uuid primary key default gen_random_uuid(),
    telegram_chat_id text not null unique,
    username text,
    first_name text,
    last_name text,
    is_active boolean not null default true,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.subscriptions (
    id bigint generated always as identity primary key,
    user_id uuid not null references public.users(id) on delete cascade,
    search_query text not null,
    label text not null,
    min_discount numeric(5,2) not null default 60,
    require_in_stock boolean not null default true,
    include_keywords_any jsonb not null default '[]'::jsonb,
    include_keywords_all jsonb not null default '[]'::jsonb,
    exclude_keywords jsonb not null default '[]'::jsonb,
    enabled boolean not null default true,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.products (
    product_id text primary key,
    store text not null,
    name text not null,
    normalized_name text not null,
    category text not null,
    url text not null,
    last_price_now integer not null,
    last_price_before integer not null,
    last_discount_percentage numeric(6,2) not null,
    last_score numeric(10,4) not null,
    historical_min_price integer not null,
    last_in_stock boolean,
    last_seen_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.price_history (
    id bigint generated always as identity primary key,
    product_id text not null references public.products(product_id) on delete cascade,
    price_now integer not null,
    price_before integer not null,
    discount_percentage numeric(6,2) not null,
    captured_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.sent_alerts (
    id bigint generated always as identity primary key,
    user_id uuid not null references public.users(id) on delete cascade,
    subscription_id bigint not null references public.subscriptions(id) on delete cascade,
    product_id text not null,
    sent_discount_percentage numeric(6,2),
    sent_at timestamptz not null default timezone('utc', now()),
    unique (user_id, subscription_id, product_id)
);

alter table public.sent_alerts
    add column if not exists sent_discount_percentage numeric(6,2);

create table if not exists public.conversation_states (
    user_id uuid primary key references public.users(id) on delete cascade,
    flow text not null,
    step text not null,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_subscriptions_user_enabled
    on public.subscriptions(user_id, enabled);

create index if not exists idx_price_history_product_captured
    on public.price_history(product_id, captured_at desc);

create index if not exists idx_sent_alerts_lookup
    on public.sent_alerts(user_id, subscription_id, sent_at desc);

create index if not exists idx_conversation_states_flow
    on public.conversation_states(flow, updated_at desc);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = timezone('utc', now());
    return new;
end;
$$;

drop trigger if exists trg_users_updated_at on public.users;
create trigger trg_users_updated_at
before update on public.users
for each row execute function public.set_updated_at();

drop trigger if exists trg_subscriptions_updated_at on public.subscriptions;
create trigger trg_subscriptions_updated_at
before update on public.subscriptions
for each row execute function public.set_updated_at();

drop trigger if exists trg_conversation_states_updated_at on public.conversation_states;
create trigger trg_conversation_states_updated_at
before update on public.conversation_states
for each row execute function public.set_updated_at();

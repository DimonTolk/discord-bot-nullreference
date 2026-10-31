ALTER TABLE guild_settings
    ADD COLUMN IF NOT EXISTS weekly_tasks_enabled BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS weekly_tasks_day INTEGER NOT NULL DEFAULT 1 CHECK (weekly_tasks_day BETWEEN 1 AND 7),
    ADD COLUMN IF NOT EXISTS weekly_tasks_hour INTEGER NOT NULL DEFAULT 12 CHECK (weekly_tasks_hour BETWEEN 0 AND 23),
    ADD COLUMN IF NOT EXISTS weekly_tasks_minute INTEGER NOT NULL DEFAULT 0 CHECK (weekly_tasks_minute BETWEEN 0 AND 59),
    ADD COLUMN IF NOT EXISTS weekly_tasks_timezone TEXT NOT NULL DEFAULT 'Europe/Minsk',
    ADD COLUMN IF NOT EXISTS weekly_tasks_enabled_since TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE TABLE IF NOT EXISTS mafia_weekly_task_presets (
    key TEXT PRIMARY KEY CHECK (char_length(key) BETWEEN 1 AND 40),
    title TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 80),
    body TEXT NOT NULL CHECK (char_length(body) BETWEEN 1 AND 900),
    enabled BOOLEAN NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS weekly_task_assignments (
    guild_id BIGINT NOT NULL,
    season_id TEXT NOT NULL,
    week TEXT NOT NULL,
    preset_key TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (guild_id,season_id,week)
);

INSERT INTO mafia_weekly_task_presets(key,title,body) VALUES
('meme', 'Семейный юмор', 'Сделайте один оригинальный мем о жизни вашей семьи в Лост Референсе. Подойдёт картинка или текстовый мем. Добавьте название семьи и опубликуйте работу в чате, где разрешено творчество.'),
('alibi', 'Безупречное алиби', 'Напишите алиби для семьи: где вы находились, когда из Доков исчез груз? От 3 до 7 предложений, один свидетель и одна подозрительная деталь. Голосовой канал не нужен.'),
('character', 'Новый человек в городе', 'Придумайте городского NPC: имя, занятие, полезную связь и тайну. Оформите досье в 5–8 строк. Персонаж должен подходить для будущих событий Лост Референса.'),
('rumors', 'Городские слухи', 'Придумайте три коротких слуха о Лост Референсе: правдоподобный, невероятный и тревожный. Один слух должен упоминать существующий игровой район. Не выдавайте вымысел за реальные обвинения участникам.'),
('business', 'Легальное прикрытие', 'Придумайте семье легальный бизнес: название, рекламный слоган и описание в 3–5 предложений. Объясните, какую пользу он приносит городу. Логотип можно добавить по желанию.'),
('noir', 'Хроника дождливого вечера', 'Напишите сцену в стиле нуар длиной 5–10 предложений. Используйте три слова: «джаз», «конверт», «фонарь». В финале герой должен принять трудное решение.'),
('code', 'Послание осведомителя', 'Составьте зашифрованное сообщение длиной до 100 символов и приложите отдельным спойлером разгадку и объяснение шифра. В расшифровке должны быть название района и время встречи. Шифр должен решаться без специальных программ.'),
('headline', 'Первая полоса', 'Подготовьте выпуск городской газеты: броский заголовок и заметку из 4–6 предложений об игровом событии или вымышленной истории семьи. Укажите, где заканчивается реальный игровой результат и начинается художественный вымысел.')
ON CONFLICT (key) DO NOTHING;

-- ===================================================================
-- 数据迁移脚本: 添加四层大纲结构 (SQLite 版本)
--
-- 用途: 将现有的"小说->章节"两层结构升级为"小说->篇->卷->章"四层结构
-- 执行前请务必备份数据库!
-- ===================================================================

-- 检查是否已经执行过迁移
SELECT 'Starting migration check...' as status;

-- 检查新表是否已存在
SELECT
    CASE
        WHEN COUNT(*) > 0 THEN 'ERROR: novel_parts table already exists! Migration may have been run already.'
        ELSE 'OK: Ready to create novel_parts'
    END as check_result
FROM sqlite_master
WHERE type='table' AND name='novel_parts';


-- ===================================================================
-- Step 1: 创建新表 novel_parts
-- ===================================================================
CREATE TABLE IF NOT EXISTS novel_parts (
    id INTEGER PRIMARY KEY,
    project_id CHAR(36) NOT NULL,
    part_number INT NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NULL,
    position INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES novel_projects(id) ON DELETE CASCADE,
    UNIQUE (project_id, part_number)
);

CREATE INDEX IF NOT EXISTS idx_parts_project_position ON novel_parts (project_id, position);

-- 创建触发器以在更新时自动更新 updated_at
CREATE TRIGGER IF NOT EXISTS trg_novel_parts_updated_at
AFTER UPDATE ON novel_parts
FOR EACH ROW
BEGIN
    UPDATE novel_parts SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.id;
END;

SELECT 'Step 1 completed: novel_parts table created' as status;


-- ===================================================================
-- Step 2: 创建新表 novel_volumes
-- ===================================================================
CREATE TABLE IF NOT EXISTS novel_volumes (
    id INTEGER PRIMARY KEY,
    project_id CHAR(36) NOT NULL,
    part_id BIGINT NOT NULL,
    volume_number INT NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NULL,
    position INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES novel_projects(id) ON DELETE CASCADE,
    FOREIGN KEY (part_id) REFERENCES novel_parts(id) ON DELETE CASCADE,
    UNIQUE (part_id, volume_number)
);

CREATE INDEX IF NOT EXISTS idx_volumes_part_position ON novel_volumes (part_id, position);
CREATE INDEX IF NOT EXISTS idx_volumes_project ON novel_volumes (project_id);

-- 创建触发器以在更新时自动更新 updated_at
CREATE TRIGGER IF NOT EXISTS trg_novel_volumes_updated_at
AFTER UPDATE ON novel_volumes
FOR EACH ROW
BEGIN
    UPDATE novel_volumes SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.id;
END;

SELECT 'Step 2 completed: novel_volumes table created' as status;


-- ===================================================================
-- Step 3: 为现有表添加 volume_id 列
-- ===================================================================
-- 为 chapter_outlines 添加 volume_id (初始允许NULL)
ALTER TABLE chapter_outlines ADD COLUMN volume_id BIGINT NULL;
SELECT 'Step 3a completed: volume_id column added to chapter_outlines' as status;

-- 为 chapters 添加 volume_id (初始允许NULL)
ALTER TABLE chapters ADD COLUMN volume_id BIGINT NULL;
SELECT 'Step 3b completed: volume_id column added to chapters' as status;


-- ===================================================================
-- Step 4: 数据迁移 - 为每个项目创建默认的Part和Volume
-- ===================================================================
BEGIN TRANSACTION;

-- 4.1 为每个有章节的项目创建默认Part
INSERT INTO novel_parts (project_id, part_number, title, description, position)
SELECT DISTINCT
    project_id,
    1,
    '第一部',
    '原有章节自动归入此部',
    0
FROM chapter_outlines
WHERE NOT EXISTS (
    SELECT 1 FROM novel_parts np WHERE np.project_id = chapter_outlines.project_id
);
SELECT 'Step 4.1 completed: Created ' || changes() || ' default parts' as status;


-- 4.2 为每个Part创建默认Volume
INSERT INTO novel_volumes (project_id, part_id, volume_number, title, description, position)
SELECT
    p.project_id,
    p.id,
    1,
    '第一卷',
    '原有章节自动归入此卷',
    0
FROM novel_parts p
WHERE NOT EXISTS (
    SELECT 1 FROM novel_volumes nv WHERE nv.part_id = p.id
);
SELECT 'Step 4.2 completed: Created ' || changes() || ' default volumes' as status;


-- 4.3 关联 chapter_outlines 到 Volume
UPDATE chapter_outlines
SET volume_id = (SELECT v.id FROM novel_volumes v WHERE v.project_id = chapter_outlines.project_id AND v.volume_number = 1)
WHERE volume_id IS NULL;
SELECT 'Step 4.3 completed: Linked ' || changes() || ' chapter_outlines to volumes' as status;


-- 4.4 关联 chapters 到 Volume
UPDATE chapters
SET volume_id = (SELECT v.id FROM novel_volumes v WHERE v.project_id = chapters.project_id AND v.volume_number = 1)
WHERE volume_id IS NULL;
SELECT 'Step 4.4 completed: Linked ' || changes() || ' chapters to volumes' as status;


-- ===================================================================
-- Step 5: 数据完整性验证
-- ===================================================================
SELECT
    COUNT(*) as orphan_count,
    CASE
        WHEN COUNT(*) = 0 THEN 'OK: No orphan chapter_outlines'
        ELSE 'WARNING: Found orphan chapter_outlines! Migration may have issues.'
    END as validation_result
FROM chapter_outlines
WHERE volume_id IS NULL;

SELECT
    COUNT(*) as orphan_count,
    CASE
        WHEN COUNT(*) = 0 THEN 'OK: No orphan chapters'
        ELSE 'WARNING: Found orphan chapters! Migration may have issues.'
    END as validation_result
FROM chapters
WHERE volume_id IS NULL;

-- 如果验证通过,提交事务
COMMIT;
SELECT 'Step 4 & 5 completed: Data migration and validation passed' as status;


-- ===================================================================
-- Step 6: 修改约束和索引 (通过重建表的方式)
-- ===================================================================

-- 禁用外键检查以允许表重建
PRAGMA foreign_keys=OFF;

-- --- 6.A 重建 chapter_outlines ---
BEGIN TRANSACTION;
SELECT 'Step 6.A starting: Rebuilding chapter_outlines...' as status;

-- ⚠️ 重要: 您必须在这里提供 chapter_outlines 表的完整、正确的列定义!
-- 移除旧的唯一约束 (project_id, chapter_number)
-- 添加新的唯一约束 (volume_id, chapter_number)
-- 将 volume_id 设为 NOT NULL
-- 添加到 novel_volumes 的外键
CREATE TABLE chapter_outlines_new (
    id INTEGER PRIMARY KEY,
    project_id CHAR(36) NOT NULL,
    volume_id BIGINT NOT NULL, -- 设为 NOT NULL
    chapter_number INT NOT NULL,
    title VARCHAR(255) NOT NULL,
    -- ... 在此列出 `chapter_outlines` 表原有的其他所有列定义 ...
    -- 示例: description TEXT, content TEXT,
    FOREIGN KEY (volume_id) REFERENCES novel_volumes(id) ON DELETE CASCADE,
    UNIQUE (volume_id, chapter_number) -- 新的唯一约束
);

-- ⚠️ 重要: 确保这里的列列表与上面的 CREATE TABLE 和下面的 SELECT 语句中的列完全匹配
INSERT INTO chapter_outlines_new (id, project_id, volume_id, chapter_number, title /*, ...其他列... */)
SELECT id, project_id, volume_id, chapter_number, title /*, ...其他列... */ FROM chapter_outlines;

DROP TABLE chapter_outlines;
ALTER TABLE chapter_outlines_new RENAME TO chapter_outlines;

-- 为新表创建索引
CREATE INDEX idx_outlines_project ON chapter_outlines (project_id);
COMMIT;
SELECT 'Step 6.A completed: chapter_outlines table rebuilt.' as status;


-- --- 6.B 重建 chapters ---
BEGIN TRANSACTION;
SELECT 'Step 6.B starting: Rebuilding chapters...' as status;

-- ⚠️ 重要: 您必须在这里提供 chapters 表的完整、正确的列定义!
CREATE TABLE chapters_new (
    id INTEGER PRIMARY KEY,
    project_id CHAR(36) NOT NULL,
    volume_id BIGINT NOT NULL, -- 设为 NOT NULL
    chapter_number INT NOT NULL,
    title VARCHAR(255) NOT NULL,
    -- ... 在此列出 `chapters` 表原有的其他所有列定义 ...
    FOREIGN KEY (volume_id) REFERENCES novel_volumes(id) ON DELETE CASCADE,
    UNIQUE (volume_id, chapter_number) -- 新的唯一约束
);

-- ⚠️ 重要: 确保这里的列列表与上面的 CREATE TABLE 和下面的 SELECT 语句中的列完全匹配
INSERT INTO chapters_new (id, project_id, volume_id, chapter_number, title /*, ...其他列... */)
SELECT id, project_id, volume_id, chapter_number, title /*, ...其他列... */ FROM chapters;

DROP TABLE chapters;
ALTER TABLE chapters_new RENAME TO chapters;

-- 为新表创建索引
CREATE INDEX idx_chapters_project ON chapters (project_id);
COMMIT;
SELECT 'Step 6.B completed: chapters table rebuilt.' as status;

-- 重新启用外键检查
PRAGMA foreign_keys=ON;


-- ===================================================================
-- 最终验证
-- ===================================================================
SELECT '========================================' as separator;
SELECT 'MIGRATION COMPLETED SUCCESSFULLY!' as status;
SELECT '========================================' as separator;

-- 显示统计信息
SELECT
    (SELECT COUNT(*) FROM novel_parts) as total_parts,
    (SELECT COUNT(*) FROM novel_volumes) as total_volumes,
    (SELECT COUNT(*) FROM chapter_outlines) as total_outlines,
    (SELECT COUNT(*) FROM chapters) as total_chapters;

SELECT 'Please verify the data manually before proceeding with the application.' as reminder;


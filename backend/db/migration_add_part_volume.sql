-- ===================================================================
-- 数据迁移脚本: 添加四层大纲结构
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
FROM information_schema.tables
WHERE table_schema = DATABASE()
AND table_name = 'novel_parts';

-- ===================================================================
-- Step 1: 创建新表 novel_parts
-- ===================================================================

CREATE TABLE IF NOT EXISTS novel_parts (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id CHAR(36) NOT NULL,
    part_number INT NOT NULL COMMENT '篇编号',
    title VARCHAR(255) NOT NULL COMMENT '篇标题',
    description TEXT NULL COMMENT '篇描述,故事走向',
    position INT DEFAULT 0 COMMENT '排序权重',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_parts_project FOREIGN KEY (project_id) REFERENCES novel_projects(id) ON DELETE CASCADE,
    UNIQUE KEY uq_part_project_number (project_id, part_number),
    INDEX idx_parts_project_position (project_id, position)
);

SELECT 'Step 1 completed: novel_parts table created' as status;

-- ===================================================================
-- Step 2: 创建新表 novel_volumes
-- ===================================================================

CREATE TABLE IF NOT EXISTS novel_volumes (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id CHAR(36) NOT NULL COMMENT '冗余字段,便于查询',
    part_id BIGINT NOT NULL,
    volume_number INT NOT NULL COMMENT 'Part内从1开始的卷编号',
    title VARCHAR(255) NOT NULL COMMENT '卷标题',
    description TEXT NULL COMMENT '卷描述,阶段性冲突',
    position INT DEFAULT 0 COMMENT '排序权重',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_volumes_project FOREIGN KEY (project_id) REFERENCES novel_projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_volumes_part FOREIGN KEY (part_id) REFERENCES novel_parts(id) ON DELETE CASCADE,
    UNIQUE KEY uq_volume_part_number (part_id, volume_number),
    INDEX idx_volumes_part_position (part_id, position),
    INDEX idx_volumes_project (project_id)
);

SELECT 'Step 2 completed: novel_volumes table created' as status;

-- ===================================================================
-- Step 3: 为现有表添加 volume_id 列
-- ===================================================================

-- 为 chapter_outlines 添加 volume_id (初始允许NULL)
ALTER TABLE chapter_outlines
    ADD COLUMN volume_id BIGINT NULL COMMENT '所属卷ID' AFTER project_id;

SELECT 'Step 3a completed: volume_id column added to chapter_outlines' as status;

-- 为 chapters 添加 volume_id (初始允许NULL)
ALTER TABLE chapters
    ADD COLUMN volume_id BIGINT NULL COMMENT '所属卷ID' AFTER project_id;

SELECT 'Step 3b completed: volume_id column added to chapters' as status;

-- ===================================================================
-- Step 4: 数据迁移 - 为每个项目创建默认的Part和Volume
-- ===================================================================

START TRANSACTION;

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

SELECT CONCAT('Step 4.1 completed: Created ', ROW_COUNT(), ' default parts') as status;

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

SELECT CONCAT('Step 4.2 completed: Created ', ROW_COUNT(), ' default volumes') as status;

-- 4.3 关联 chapter_outlines 到 Volume
UPDATE chapter_outlines co
INNER JOIN novel_volumes v ON co.project_id = v.project_id AND v.volume_number = 1
SET co.volume_id = v.id
WHERE co.volume_id IS NULL;

SELECT CONCAT('Step 4.3 completed: Linked ', ROW_COUNT(), ' chapter_outlines to volumes') as status;

-- 4.4 关联 chapters 到 Volume
UPDATE chapters c
INNER JOIN novel_volumes v ON c.project_id = v.project_id AND v.volume_number = 1
SET c.volume_id = v.id
WHERE c.volume_id IS NULL;

SELECT CONCAT('Step 4.4 completed: Linked ', ROW_COUNT(), ' chapters to volumes') as status;

-- ===================================================================
-- Step 5: 数据完整性验证
-- ===================================================================

-- 检查是否有孤立的 chapter_outlines
SELECT
    COUNT(*) as orphan_count,
    CASE
        WHEN COUNT(*) = 0 THEN 'OK: No orphan chapter_outlines'
        ELSE 'WARNING: Found orphan chapter_outlines! Migration may have issues.'
    END as validation_result
FROM chapter_outlines
WHERE volume_id IS NULL;

-- 检查是否有孤立的 chapters
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

SELECT 'Step 5 completed: Data integrity validation passed' as status;

-- ===================================================================
-- Step 6: 修改约束和索引
-- ===================================================================

-- 6.1 设置 volume_id 为 NOT NULL
ALTER TABLE chapter_outlines
    MODIFY COLUMN volume_id BIGINT NOT NULL;

SELECT 'Step 6.1a completed: Set volume_id to NOT NULL for chapter_outlines' as status;

ALTER TABLE chapters
    MODIFY COLUMN volume_id BIGINT NOT NULL;

SELECT 'Step 6.1b completed: Set volume_id to NOT NULL for chapters' as status;

-- 6.2 删除旧的唯一约束
ALTER TABLE chapter_outlines
    DROP KEY uq_outline_project_chapter;

SELECT 'Step 6.2a completed: Dropped old unique constraint from chapter_outlines' as status;

ALTER TABLE chapters
    DROP KEY uq_chapter_project_number;

SELECT 'Step 6.2b completed: Dropped old unique constraint from chapters' as status;

-- 6.3 添加新的唯一约束
ALTER TABLE chapter_outlines
    ADD UNIQUE KEY uq_outline_volume_chapter (volume_id, chapter_number);

SELECT 'Step 6.3a completed: Added new unique constraint to chapter_outlines' as status;

ALTER TABLE chapters
    ADD UNIQUE KEY uq_chapter_volume_number (volume_id, chapter_number);

SELECT 'Step 6.3b completed: Added new unique constraint to chapters' as status;

-- 6.4 添加外键约束
ALTER TABLE chapter_outlines
    ADD CONSTRAINT fk_outlines_volume
    FOREIGN KEY (volume_id) REFERENCES novel_volumes(id) ON DELETE CASCADE;

SELECT 'Step 6.4a completed: Added foreign key constraint to chapter_outlines' as status;

ALTER TABLE chapters
    ADD CONSTRAINT fk_chapters_volume
    FOREIGN KEY (volume_id) REFERENCES novel_volumes(id) ON DELETE CASCADE;

SELECT 'Step 6.4b completed: Added foreign key constraint to chapters' as status;

-- 6.5 添加project索引(优化查询性能)
ALTER TABLE chapter_outlines
    ADD INDEX idx_outlines_project (project_id);

SELECT 'Step 6.5a completed: Added project index to chapter_outlines' as status;

ALTER TABLE chapters
    ADD INDEX idx_chapters_project (project_id);

SELECT 'Step 6.5b completed: Added project index to chapters' as status;

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

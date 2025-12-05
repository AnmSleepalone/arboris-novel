-- ===================================================================
-- 回滚脚本: 撤销四层大纲结构迁移
--
-- 用途: 将"小说->篇->卷->章"四层结构回滚到"小说->章节"两层结构
-- 警告: 执行此脚本将删除所有Part和Volume数据!
-- 执行前请务必备份数据库!
-- ===================================================================

SELECT '========================================' as separator;
SELECT 'WARNING: This will delete all Part and Volume data!' as warning;
SELECT 'Press Ctrl+C to cancel within 5 seconds...' as warning;
SELECT '========================================' as separator;

-- 等待用户确认 (需要手动执行)
-- DO SLEEP(5);

START TRANSACTION;

-- ===================================================================
-- Step 1: 移除外键约束
-- ===================================================================

ALTER TABLE chapter_outlines
    DROP FOREIGN KEY fk_outlines_volume;

SELECT 'Step 1.1 completed: Dropped foreign key from chapter_outlines' as status;

ALTER TABLE chapters
    DROP FOREIGN KEY fk_chapters_volume;

SELECT 'Step 1.2 completed: Dropped foreign key from chapters' as status;

-- ===================================================================
-- Step 2: 删除新的唯一约束
-- ===================================================================

ALTER TABLE chapter_outlines
    DROP KEY uq_outline_volume_chapter;

SELECT 'Step 2.1 completed: Dropped unique constraint from chapter_outlines' as status;

ALTER TABLE chapters
    DROP KEY uq_chapter_volume_number;

SELECT 'Step 2.2 completed: Dropped unique constraint from chapters' as status;

-- ===================================================================
-- Step 3: 删除新增的索引
-- ===================================================================

ALTER TABLE chapter_outlines
    DROP INDEX idx_outlines_project;

SELECT 'Step 3.1 completed: Dropped project index from chapter_outlines' as status;

ALTER TABLE chapters
    DROP INDEX idx_chapters_project;

SELECT 'Step 3.2 completed: Dropped project index from chapters' as status;

-- ===================================================================
-- Step 4: 删除 volume_id 列
-- ===================================================================

ALTER TABLE chapter_outlines
    DROP COLUMN volume_id;

SELECT 'Step 4.1 completed: Dropped volume_id from chapter_outlines' as status;

ALTER TABLE chapters
    DROP COLUMN volume_id;

SELECT 'Step 4.2 completed: Dropped volume_id from chapters' as status;

-- ===================================================================
-- Step 5: 恢复原有的唯一约束
-- ===================================================================

ALTER TABLE chapter_outlines
    ADD UNIQUE KEY uq_outline_project_chapter (project_id, chapter_number);

SELECT 'Step 5.1 completed: Restored unique constraint to chapter_outlines' as status;

ALTER TABLE chapters
    ADD UNIQUE KEY uq_chapter_project_number (project_id, chapter_number);

SELECT 'Step 5.2 completed: Restored unique constraint to chapters' as status;

-- ===================================================================
-- Step 6: 删除新表 (级联删除数据)
-- ===================================================================

DROP TABLE IF EXISTS novel_volumes;

SELECT 'Step 6.1 completed: Dropped novel_volumes table' as status;

DROP TABLE IF EXISTS novel_parts;

SELECT 'Step 6.2 completed: Dropped novel_parts table' as status;

-- ===================================================================
-- 验证回滚结果
-- ===================================================================

-- 检查表是否已删除
SELECT
    CASE
        WHEN COUNT(*) = 0 THEN 'OK: novel_parts table removed'
        ELSE 'ERROR: novel_parts table still exists!'
    END as validation_result
FROM information_schema.tables
WHERE table_schema = DATABASE()
AND table_name = 'novel_parts';

SELECT
    CASE
        WHEN COUNT(*) = 0 THEN 'OK: novel_volumes table removed'
        ELSE 'ERROR: novel_volumes table still exists!'
    END as validation_result
FROM information_schema.tables
WHERE table_schema = DATABASE()
AND table_name = 'novel_volumes';

-- 检查volume_id列是否已删除
SELECT
    CASE
        WHEN COUNT(*) = 0 THEN 'OK: volume_id column removed from chapter_outlines'
        ELSE 'ERROR: volume_id column still exists in chapter_outlines!'
    END as validation_result
FROM information_schema.columns
WHERE table_schema = DATABASE()
AND table_name = 'chapter_outlines'
AND column_name = 'volume_id';

SELECT
    CASE
        WHEN COUNT(*) = 0 THEN 'OK: volume_id column removed from chapters'
        ELSE 'ERROR: volume_id column still exists in chapters!'
    END as validation_result
FROM information_schema.columns
WHERE table_schema = DATABASE()
AND table_name = 'chapters'
AND column_name = 'volume_id';

COMMIT;

SELECT '========================================' as separator;
SELECT 'ROLLBACK COMPLETED SUCCESSFULLY!' as status;
SELECT '========================================' as separator;

-- 显示统计信息
SELECT
    (SELECT COUNT(*) FROM chapter_outlines) as total_outlines,
    (SELECT COUNT(*) FROM chapters) as total_chapters;

SELECT 'Database has been rolled back to two-layer structure (Project -> Chapter)' as result;
SELECT 'All Part and Volume data has been permanently deleted!' as warning;

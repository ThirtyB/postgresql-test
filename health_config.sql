-- 健康度配置表
CREATE TABLE IF NOT EXISTS health_config (
    id SERIAL PRIMARY KEY,
    config_key VARCHAR(100) UNIQUE NOT NULL,
    config_value NUMERIC(10,2) NOT NULL,
    config_description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 插入默认配置值
INSERT INTO health_config (config_key, config_value, config_description) VALUES
    ('cpu_warning_threshold', 90.00, 'CPU使用率警告阈值（%），达到此值将标记为警告状态'),
    ('cpu_alert_threshold', 70.00, 'CPU使用率提示阈值（%），达到此值将标记为提示状态'),
    ('memory_warning_threshold', 90.00, '内存使用率警告阈值（%），达到此值将标记为警告状态'),
    ('memory_alert_threshold', 70.00, '内存使用率提示阈值（%），达到此值将标记为提示状态'),
    ('disk_warning_threshold', 90.00, '磁盘使用率警告阈值（%），达到此值将标记为警告状态'),
    ('disk_alert_threshold', 70.00, '磁盘使用率提示阈值（%），达到此值将标记为提示状态'),
    ('swap_warning_threshold', 50.00, 'Swap使用率警告阈值（%），达到此值将标记为警告状态'),
    ('swap_alert_threshold', 20.00, 'Swap使用率提示阈值（%），达到此值将标记为提示状态'),
    ('network_warning_threshold', 90.00, '网络使用率警告阈值（%），达到此值将标记为警告状态'),
    ('network_alert_threshold', 70.00, '网络使用率提示阈值（%），达到此值将标记为提示状态'),
    ('data_freshness_warning_hours', 1.00, '数据新鲜度警告阈值（小时），超过此时间将标记为警告状态'),
    ('data_freshness_alert_hours', 0.30, '数据新鲜度提示阈值（小时），超过此时间将标记为提示状态'),
    ('cpu_weight', 0.20, 'CPU权重，影响健康评分的计算（0-1之间）'),
    ('memory_weight', 0.20, '内存权重，影响健康评分的计算（0-1之间）'),
    ('disk_weight', 0.20, '磁盘权重，影响健康评分的计算（0-1之间）'),
    ('swap_weight', 0.15, 'Swap权重，影响健康评分的计算（0-1之间）'),
    ('network_weight', 0.15, '网络权重，影响健康评分的计算（0-1之间）'),
    ('freshness_weight', 0.10, '数据新鲜度权重，影响健康评分的计算（0-1之间）'),
    ('network_base_bandwidth_mbps', 1000.00, '基准网络带宽（Mbps），用于计算网络使用率'),
    ('network_score_threshold', 80.00, '网络评分阈值（%），低于此值开始扣分'),
    ('freshness_score_decay_rate', 20.00, '数据新鲜度评分衰减率（分/小时），每超过1小时减多少分'),
    -- 新增评分配置参数
    ('normal_range_score_base', 80.00, '正常范围基础评分（0-100）'),
    ('alert_range_score_base', 50.00, '提示范围基础评分（0-100）'),
    ('warning_range_score_base', 20.00, '警告范围基础评分（0-100）'),
    ('normal_range_penalty_rate', 0.20, '正常范围扣分率（每1%使用率扣分比例）'),
    ('alert_range_penalty_rate', 0.30, '提示范围扣分率（每1%使用率扣分比例）'),
    ('warning_range_penalty_rate', 0.50, '警告范围扣分率（每1%使用率扣分比例）'),
    ('swap_multiplier', 2.00, 'Swap使用率影响倍数'),
    ('network_penalty_multiplier', 2.00, '网络使用率超过阈值后的扣分倍数')
ON CONFLICT (config_key) DO NOTHING;
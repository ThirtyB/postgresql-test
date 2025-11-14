/*
 Navicat Premium Data Transfer

 Source Server         : connection1
 Source Server Type    : PostgreSQL
 Source Server Version : 180000 (180000)
 Source Host           : 192.168.16.104:5432
 Source Catalog        : db1
 Source Schema         : public

 Target Server Type    : PostgreSQL
 Target Server Version : 180000 (180000)
 File Encoding         : 65001

 Date: 06/11/2025 22:27:45
*/


-- ----------------------------
-- Create sequence for node_monitor_metrics table
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."node_monitor_metrics_id_seq" CASCADE;
CREATE SEQUENCE "public"."node_monitor_metrics_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- ----------------------------
-- Table structure for node_monitor_metrics
-- ----------------------------
DROP TABLE IF EXISTS "public"."node_monitor_metrics";
CREATE TABLE "public"."node_monitor_metrics" (
  "id" int8 NOT NULL DEFAULT nextval('node_monitor_metrics_id_seq'::regclass),
  "ip" text COLLATE "pg_catalog"."default" NOT NULL,
  "ts" int8 NOT NULL,
  "cpu_usr" float8,
  "cpu_sys" float8,
  "cpu_iow" float8,
  "mem_total" int8,
  "mem_free" int8,
  "mem_buff" int8,
  "mem_cache" int8,
  "swap_total" int8,
  "swap_used" int8,
  "swap_in" int8,
  "swap_out" int8,
  "system_in" int8,
  "system_cs" int8,
  "disk_name" text COLLATE "pg_catalog"."default",
  "disk_total" int8,
  "disk_used" int8,
  "disk_used_percent" float8,
  "disk_iops" int8,
  "disk_r" int8,
  "disk_w" int8,
  "net_rx_kbytes" float8,
  "net_tx_kbytes" float8,
  "net_rx_kbps" float8,
  "net_tx_kbps" float8,
  "version" text COLLATE "pg_catalog"."default",
  "inserted_at" timestamptz(6) NOT NULL DEFAULT now()
)
;

-- ----------------------------
-- Indexes structure for table node_monitor_metrics
-- ----------------------------
CREATE INDEX "idx_node_monitor_metrics_ip" ON "public"."node_monitor_metrics" USING btree (
  "ip" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
CREATE INDEX "idx_node_monitor_metrics_ts" ON "public"."node_monitor_metrics" USING btree (
  "ts" "pg_catalog"."int8_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table node_monitor_metrics
-- ----------------------------
ALTER TABLE "public"."node_monitor_metrics" ADD CONSTRAINT "node_monitor_metrics_pkey" PRIMARY KEY ("id");

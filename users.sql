/*
 Navicat Premium Data Transfer

 Source Server         : connection1
 Source Server Type    : PostgreSQL
 Source Server Version : 180000 (180000)
 Source Host           : 192.168.16.106:5432
 Source Catalog        : db1
 Source Schema         : public

 Target Server Type    : PostgreSQL
 Target Server Version : 180000 (180000)
 File Encoding         : 65001

 Date: 08/11/2025 20:10:06
*/


-- ----------------------------
-- Create sequence for users table
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."users_id_seq" CASCADE;
CREATE SEQUENCE "public"."users_id_seq"
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- ----------------------------
-- Create trigger function for updated_at
-- ----------------------------
CREATE OR REPLACE FUNCTION "public"."update_updated_at_column"()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- ----------------------------
-- Table structure for users
-- ----------------------------
DROP TABLE IF EXISTS "public"."users";
CREATE TABLE "public"."users" (
  "id" int4 NOT NULL DEFAULT nextval('users_id_seq'::regclass),
  "username" varchar(50) COLLATE "pg_catalog"."default" NOT NULL,
  "password_hash" varchar(255) COLLATE "pg_catalog"."default" NOT NULL,
  "role" varchar(20) COLLATE "pg_catalog"."default" DEFAULT 'user'::character varying,
  "is_active" bool DEFAULT true,
  "last_login" timestamptz(6),
  "created_at" timestamptz(6) DEFAULT now(),
  "updated_at" timestamptz(6) DEFAULT now()
)
;
COMMENT ON COLUMN "public"."users"."id" IS '用户ID';
COMMENT ON COLUMN "public"."users"."username" IS '用户名（唯一）';
COMMENT ON COLUMN "public"."users"."password_hash" IS '密码哈希值（非明文）';
COMMENT ON COLUMN "public"."users"."role" IS '用户角色：admin-管理员, user-普通用户, viewer-只读用户';
COMMENT ON COLUMN "public"."users"."is_active" IS '是否激活';
COMMENT ON COLUMN "public"."users"."last_login" IS '最后登录时间';
COMMENT ON COLUMN "public"."users"."created_at" IS '创建时间';
COMMENT ON COLUMN "public"."users"."updated_at" IS '更新时间';
COMMENT ON TABLE "public"."users" IS '用户表 - 存储用户认证信息';

-- ----------------------------
-- Indexes structure for table users
-- ----------------------------
CREATE INDEX "idx_users_is_active" ON "public"."users" USING btree (
  "is_active" "pg_catalog"."bool_ops" ASC NULLS LAST
);
CREATE INDEX "idx_users_role" ON "public"."users" USING btree (
  "role" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
CREATE INDEX "idx_users_username" ON "public"."users" USING btree (
  "username" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);

-- ----------------------------
-- Triggers structure for table users
-- ----------------------------
CREATE TRIGGER "update_users_updated_at" BEFORE UPDATE ON "public"."users"
FOR EACH ROW
EXECUTE PROCEDURE "public"."update_updated_at_column"();

-- ----------------------------
-- Uniques structure for table users
-- ----------------------------
ALTER TABLE "public"."users" ADD CONSTRAINT "users_username_key" UNIQUE ("username");

-- ----------------------------
-- Checks structure for table users
-- ----------------------------
ALTER TABLE "public"."users" ADD CONSTRAINT "users_role_check" CHECK (role::text = ANY (ARRAY['admin'::character varying, 'user'::character varying]::text[]));

-- ----------------------------
-- Primary Key structure for table users
-- ----------------------------
ALTER TABLE "public"."users" ADD CONSTRAINT "users_pkey" PRIMARY KEY ("id");

# Rollback Guide - Azure Container App

## 1. Mục tiêu

Tài liệu này hướng dẫn rollback Azure Container App về image version trước đó nếu bản deploy mới bị lỗi.

## 2. Image tagging strategy

GitHub Actions build image với tag là 7 ký tự đầu của commit SHA.

Ví dụ:

```text
acrdsrapi31862.azurecr.io/dsr-api:3ffb2ad
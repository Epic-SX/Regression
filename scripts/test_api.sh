#!/usr/bin/env bash

# PublicApiEndpoint をここに貼り付けるか、環境変数から取得する
ENDPOINT="https://k3nainixy0.execute-api.ap-northeast-1.amazonaws.com/Prod"

# 新規作成時に受け取る id を一時保存する変数
NEW_ID=""

echo "--------------------------------------------------"
echo "1) 全件取得 (GET /koenoto)"
echo "--------------------------------------------------"
curl -X GET "$ENDPOINT/koenoto"
echo ""
echo ""

echo "--------------------------------------------------"
echo "2) 新規作成 (POST /koenoto)"
echo "--------------------------------------------------"
RESPONSE=$(curl -s -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "testuser",
    "title": "会議の録音",
    "date": "2025-02-01",
    "duration": "45:00",
    "transcript": "テスト用文字起こし",
    "summary": "テスト用要約",
    "points": "テスト用要点",
    "keywords": ["キーワード1","キーワード2"]
  }' \
  "$ENDPOINT/koenoto")

echo "RESPONSE: $RESPONSE"
echo ""

# JSON から id を取り出す (jq 必須) 
NEW_ID=$(echo "$RESPONSE" | jq -r '.item.id')
echo "取得したID: $NEW_ID"
echo ""

echo "--------------------------------------------------"
echo "3) 作成したアイテムを取得 (GET /koenoto/{id})"
echo "--------------------------------------------------"
curl -X GET "$ENDPOINT/koenoto/$NEW_ID"
echo ""
echo ""

echo "--------------------------------------------------"
echo "4) アイテムを更新 (PUT /koenoto/{id})"
echo "--------------------------------------------------"
curl -X PUT \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "testuser",
    "title": "更新後タイトル",
    "date": "2025-02-02",
    "duration": "50:00",
    "transcript": "更新された文字起こし",
    "summary": "更新された要約",
    "points": "更新された要点",
    "keywords": ["更新キーワード1","更新キーワード2"]
  }' \
  "$ENDPOINT/koenoto/$NEW_ID"
echo ""
echo ""

echo "--------------------------------------------------"
echo "5) 更新後のアイテムを取得 (GET /koenoto/{id})"
echo "--------------------------------------------------"
curl -X GET "$ENDPOINT/koenoto/$NEW_ID"
echo ""
echo ""

echo "--------------------------------------------------"
echo "6) アイテムを削除 (DELETE /koenoto/{id})"
echo "--------------------------------------------------"
curl -X DELETE "$ENDPOINT/koenoto/$NEW_ID"
echo ""
echo ""

echo "--------------------------------------------------"
echo "Testing audio processing with existing S3 file"
echo "--------------------------------------------------"
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "audioKeys": ["your-existing-file.wav"],
    "userId": "test-user"
  }' \
  "$ENDPOINT/koenoto/process-audio"
echo ""
echo ""

echo "--------------------------------------------------"
echo "完了"
echo "--------------------------------------------------"

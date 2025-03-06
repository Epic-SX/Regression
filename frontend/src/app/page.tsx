"use client";
import {
  Check,
  ChevronRight,
  Clock,
  FileSearch,
  FileText,
  Menu,
  Mic,
  Square,
  Trash2,
} from "lucide-react";
import { useEffect, useRef, useState, useCallback } from "react";
import { v4 as uuid } from "uuid";

/* eslint-disable @typescript-eslint/no-unused-vars */

interface Recording {
  id: string;
  title: string;
  date: string;
  start_time: string;
  duration: string;
  transcript?: string;
  summary?: string;
  keywords?: string[];
  user_id?: string;
  audioUrl?: string;
  audioChunksUrls?: string[];
}

interface RecordingPayload {
  title: string;
  date: string;
  start_time: string;
  duration: string;
  transcript: string;
  summary: string;
  keywords: string[];
  user_id: string;
  audioUrl?: string;
}

// Remove or comment out the BlobEvent interface if not used
/* interface BlobEvent {
  data: Blob;
  timecode?: number;
} */

const KOENOTE_API_URL = process.env.NEXT_PUBLIC_KOENOTE_API_URL || "";
const AUDIO_BUCKET_NAME = process.env.NEXT_PUBLIC_AUDIO_BUCKET_NAME || "";

// Remove or use the CHUNK_SIZE constant
// const CHUNK_SIZE = 2 * 1024 * 1024; // 2MB chunks

const formatDateTime = (date: string, time: string) => {
  if (!date || !time) return "";
  const dateTime = new Date(`${date}T${time}`);
  if (isNaN(dateTime.getTime())) {
    return "";
  }

  return dateTime.toLocaleString("ja-JP", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
};

const StatusIndicator = ({ status, processingStatus }: { status: string, processingStatus?: string | null }) => {
  if (!status && !processingStatus) return null;
  
  const displayStatus = processingStatus || status;

  return (
    <div className="flex justify-center">
      <div className="relative flex items-center gap-3 bg-zinc-800 text-zinc-100 px-4 py-2 rounded-full text-xs sm:text-sm shadow-lg">
        <div className="flex items-center gap-1">
          {[...Array(3)].map((_, i) => (
            <div
              key={i}
              className="w-1 h-1 bg-zinc-300 rounded-full animate-pulse"
              style={{
                animationDelay: `${i * 0.15}s`,
                opacity: displayStatus.includes("中") || processingStatus ? 1 : 0,
              }}
            />
          ))}
        </div>
        <span className="relative">
          {displayStatus}
          {(displayStatus.includes("中") || processingStatus) && (
            <div className="absolute top-0 left-0 w-full h-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-transparent via-white/20 to-transparent"
                style={{
                  animation: "shimmer 1s infinite",
                  width: "200%",
                  transform: "translateX(-50%)",
                }}
              />
            </div>
          )}
        </span>
      </div>
    </div>
  );
};

const RecordButton = ({
  isRecording,
  onClick,
}: {
  isRecording: boolean;
  onClick: () => void;
}) => {
  return (
    <button
      onClick={onClick}
      className={`
       relative
       group
       px-8 py-6
       rounded-full
       transition-all
       duration-300
       hover:scale-105
       focus:outline-none
       focus:ring-2 
       focus:ring-zinc-400
       focus:ring-offset-2
       ${
         isRecording
           ? "bg-zinc-900 hover:bg-zinc-800"
           : "bg-zinc-800 hover:bg-zinc-700"
       }
     `}
    >
      <div className="flex items-center text-white">
        <div className="relative">
          {isRecording ? (
            <>
              <Square className="mr-2" size={20} />
              <span className="absolute -top-1 -right-1 h-3 w-3">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-zinc-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-3 w-3 bg-red-500" />
              </span>
            </>
          ) : (
            <Mic
              className={`mr-2 ${isRecording ? "animate-pulse" : ""}`}
              size={20}
            />
          )}
        </div>
        <span className="font-medium">
          {isRecording ? "録音停止" : "録音開始"}
        </span>
      </div>

      {isRecording && (
        <div className="absolute -bottom-4 left-1/2 transform -translate-x-1/2">
          <div className="flex items-center space-x-1">
            {[...Array(5)].map((_, i) => (
              <div
                key={i}
                className="w-0.5 h-4 bg-red-400"
                style={{
                  animation: `wave 1s ease-in-out infinite`,
                  animationDelay: `${i * 0.1}s`,
                }}
              />
            ))}
          </div>
        </div>
      )}
    </button>
  );
};

const KoenotoApp = () => {
  const [isRecording, setIsRecording] = useState(false);
  const [status, setStatus] = useState("");
  const [selectedRecording, setSelectedRecording] = useState<Recording | null>(
    null
  );
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [isEditingBeforeSave, setIsEditingBeforeSave] = useState(false);
  const [title, setTitle] = useState("");
  const [transcript, setTranscript] = useState("");
  const [summary, setSummary] = useState("");
  const [keywords, setKeywords] = useState<string[]>([]);
  const [recordingStartTime, setRecordingStartTime] = useState<Date | null>(
    null
  );
  const [recordingDuration, setRecordingDuration] = useState<string>("0:00");
  const [uploadedAudioUrl, setUploadedAudioUrl] = useState<string>("");

  const [/* recorder */, /* setRecorder */] = useState<MediaRecorder | null>(null);

  const recordingChunks = useRef<Blob[]>([]);
  const [audioChunks, setAudioChunks] = useState<string[]>([]);
  const [currentChunkIndex, setCurrentChunkIndex] = useState<number>(0);
  const audioRef = useRef<HTMLAudioElement>(null);

  const USER_ID = "demo-user-123";

  const [executionArn, setExecutionArn] = useState<string | null>(null); // Used for tracking Step Functions execution
  const [processingStatus, setProcessingStatus] = useState<string | null>(null);
  const [pollingInterval, setPollingInterval] = useState<NodeJS.Timeout | null>(null);

  const recordingStartTimeRef = useRef<number | null>(null);
  const recordingIntervalRef = useRef<NodeJS.Timeout | null>(null);

  const mediaRecorder = useRef<MediaRecorder | null>(null);

  const [currentProcessingSessionId, /* setCurrentProcessingSessionId */] = useState<string | null>(null);

  // If it's not used anywhere, we can comment it out
  // const processingCheckInterval = useRef<NodeJS.Timeout | null>(null);

  const [/* errorMessage */, setErrorMessage] = useState<string | null>(null);

  const [isLoading, setIsLoading] = useState(false);

  const [showAudioPlayer, setShowAudioPlayer] = useState(false);

  const [/* structuredSentences */, /* setStructuredSentences */] = useState<Array<{
    text: string;
    start_time: number;
    end_time: number;
  }>>([]);

  const fetchRecordings = async () => {
    try {
      setStatus("一覧取得中...");
      const res = await fetch(`${KOENOTE_API_URL}/koenoto?user_id=${USER_ID}`);
      if (!res.ok) {
        throw new Error(`一覧取得に失敗しました (status: ${res.status})`);
      }
      const data: Recording[] = await res.json();
      const sortedData = data.sort((a, b) => {
        const dateA = new Date(`${a.date} ${a.start_time}`);
        const dateB = new Date(`${b.date} ${b.start_time}`);
        return dateB.getTime() - dateA.getTime();
      });
      setRecordings(sortedData);
      setStatus("");
    } catch (error) {
      setStatus(
        "一覧取得に失敗: " + (error instanceof Error ? error.message : "")
      );
    }
  };

  useEffect(() => {
    const styleSheet = document.createElement("style");
    styleSheet.innerText = `
      @keyframes wave {
        0%, 100% { height: 4px; }
        50% { height: 16px; }
      }
      @keyframes shimmer {
        100% { transform: translateX(50%); }
      }
    `;
    document.head.appendChild(styleSheet);

    fetchRecordings();

    return () => styleSheet.remove();
  }, []);


  const uploadChunks = async (chunks: Blob[]): Promise<string[]> => {
    const uploadedUrls: string[] = [];
    
    for (let i = 0; i < chunks.length; i++) {
      try {
        setStatus(`チャンク ${i+1}/${chunks.length} をアップロード中...`);
      const chunk = chunks[i];
        
        // WebM形式をそのまま使用
        const extension = chunk.type.includes('webm') ? 'webm' : 'wav';
        const contentType = chunk.type.includes('webm') ? 'audio/webm' : 'audio/wav';
        
        // ファイル名を生成（一意になるようにタイムスタンプとインデックスを含める）
        const filename = `chunk_${Date.now()}_${i}.${extension}`;
        
        console.log(`Uploading chunk ${i+1} as ${contentType}, size: ${chunk.size/1024/1024} MB`);
        
        // プリサインドURLを取得
        const presignedUrlResponse = await fetch(`${KOENOTE_API_URL}/koenoto/presigned-url`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            filename: filename,
            contentType: contentType
          }),
        });
        
        if (!presignedUrlResponse.ok) {
          throw new Error(`プリサインドURLの取得に失敗しました: ${presignedUrlResponse.status}`);
        }
        
        const presignedData = await presignedUrlResponse.json();
        console.log("Presigned URL response:", presignedData);
        
        // バックエンドのレスポンス形式に合わせて調整
        const presignedUrl = presignedData.presignedUrl;
        let key = presignedData.key;
        if (!key && presignedData.audioUrl) {
          // audioUrl から S3 キーを抽出 (URL の最後の部分)
          key = presignedData.audioUrl.split('/').pop();
        }
        
        if (!presignedUrl || !key) {
          console.error("Invalid presigned URL response:", presignedData);
          throw new Error(`プリサインドURLまたはキーが取得できませんでした`);
        }
        
        console.log(`Got presigned URL for chunk ${i}, key: ${key}`);
        
        // S3にアップロード
        const uploadResponse = await fetch(presignedUrl, {
          method: "PUT",
          headers: { "Content-Type": contentType },
          body: chunk,
        });
        
        if (!uploadResponse.ok) {
          throw new Error(`チャンク ${i+1} のアップロードに失敗しました: ${uploadResponse.status}`);
        }
        
        // アップロード成功したら、S3のキーを保存
        uploadedUrls.push(key);
        console.log(`Successfully uploaded chunk ${i} with key ${key}`);
      } catch (error) {
        console.error(`Error uploading chunk ${i}:`, error);
        throw error;
      }
    }
    
    return uploadedUrls;
  };

  const createChunks = (audioBlob: Blob): Blob[] => {
    // For very large recordings, we need to split into manageable chunks
    // Target chunk size is 10MB (smaller than the 25MB limit for Whisper API)
    const MAX_CHUNK_SIZE = 0.1 * 1024 * 1024; // 10MB
    
    if (audioBlob.size <= MAX_CHUNK_SIZE) {
      console.log(`Audio size (${audioBlob.size / 1024 / 1024} MB) is smaller than chunk size, not splitting`);
      return [audioBlob];
    }
    
    console.log(`Creating chunks from ${audioBlob.size / 1024 / 1024} MB audio`);
    
    // For large files, split into multiple chunks based on size
    // const chunks: Blob[] = [];
    const chunkCount = Math.ceil(audioBlob.size / MAX_CHUNK_SIZE);
    
    // Create time-based chunks (approximate)
    const audioDuration = recordingDuration ? parseInt(recordingDuration.toString()) : 60;
    const secondsPerChunk = Math.ceil(audioDuration / chunkCount);
    
    console.log(`Splitting ${audioDuration}s audio into ${chunkCount} chunks of ~${secondsPerChunk}s each`);
    
    // We'll return the original blob and let the backend handle the splitting
    // This is because browser-side splitting of WebM is complex
    return [audioBlob];
  };

  const processAudio = async (audioBlob: Blob) => {
    try {
      setStatus("音声処理中...");
      
      // 音声形式を確認
      console.log(`Processing audio: ${audioBlob.type}, size: ${audioBlob.size/1024/1024} MB`);
      
      // チャンクを作成
      const chunks = createChunks(audioBlob);
      console.log(`Created ${chunks.length} chunks`);
      
      // チャンクをアップロード
      const chunkKeys = await uploadChunks(chunks);
      console.log(`Uploaded ${chunkKeys.length} chunks, Keys:`, chunkKeys);
      
      if (chunkKeys.length === 0) {
        throw new Error("音声ファイルのアップロードに失敗しました");
      }
      
      // Generate audio URLs for the chunks
      const chunkUrls = chunkKeys.map(
        (key: string) => `https://${AUDIO_BUCKET_NAME}.s3.amazonaws.com/${key}`
      );
      
      // Set the audio chunks for playback
      setAudioChunks(chunkUrls);
      setCurrentChunkIndex(0);
      setShowAudioPlayer(true);
      
      // 処理開始
      setStatus("音声処理開始中...");
      setProcessingStatus("処理を開始しています...");
      
      const response = await fetch(`${KOENOTE_API_URL}/koenoto/process-audio`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          audioKeys: chunkKeys,
          completeAudioUrl: null,
          userId: USER_ID
        }),
      });
      
      if (!response.ok) {
        const errorData = await response.json();
        console.error("API error:", errorData);
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorData.error || 'Unknown error'}`);
      }
      
      const result = await response.json();
      console.log("Process audio response:", result);
      
      // Check if we got an execution ARN (Step Functions workflow)
      if (result.executionArn) {
        // Start polling for status updates
        setExecutionArn(result.executionArn);
        startPolling(result.executionArn);
        setStatus("");
        setProcessingStatus("音声処理中...");
        return null; // Results will come later via polling
      } else if (result.title) {
        // We got immediate results
        setTitle(result.title || "無題");
        setTranscript(result.transcript || "");
        setSummary(result.summary || "");
        setKeywords(result.keywords || []);
        setStatus("処理完了");
        setProcessingStatus(null);
        
        // Set showAudioPlayer to true if we have audio data
        if (result.audioUrl) {
          setUploadedAudioUrl(result.audioUrl);
          setShowAudioPlayer(true);
        }
        
        // Important: Set isEditingBeforeSave to true to display the editing form
        setIsEditingBeforeSave(true);
        
        // 録音一覧を更新
        fetchRecordings();
        
        return result;
      } else {
        throw new Error("予期しないレスポンス形式です");
      }
    } catch (error) {
      console.error("Processing error:", error);
      setStatus("音声処理に失敗しました: " + (error instanceof Error ? error.message : ""));
      setProcessingStatus(null);
      throw error;
    }
  };

  // If this function is not used, you can comment it out or remove it
  /* const createKoenoteItem = async () => {
    try {
      setStatus("サーバーに保存中...");
      const now = new Date();

      const payload: RecordingPayload = {
        title,
        date: now.toISOString().split("T")[0],
        start_time: now.toTimeString().split(" ")[0],
        duration: recordingDuration ? recordingDuration.toString() : "0",
        transcript: transcript || "",
        summary: summary || "",
        keywords: keywords || [],
        user_id: USER_ID,  // Use the constant USER_ID instead of "default"
        audioUrl: uploadedAudioUrl
      };

      const res = await fetch(`${KOENOTE_API_URL}/koenoto`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        throw new Error(`POSTに失敗しました (status: ${res.status})`);
      }

      const data = await res.json();
      const newItem: Recording = data.item;

      // Update the recordings list with the new item
      setRecordings(prevRecordings => {
        const updatedRecordings = [newItem, ...prevRecordings];
        return updatedRecordings.sort((a, b) => {
          const dateA = new Date(`${a.date} ${a.start_time}`);
          const dateB = new Date(`${b.date} ${b.start_time}`);
          return dateB.getTime() - dateA.getTime();
        });
      });

      setStatus("サーバー保存完了");
      setSelectedRecording(newItem);
      setTranscript(newItem.transcript || "");
      setSummary(newItem.summary || "");
      setKeywords(newItem.keywords || []);
      setTitle(newItem.title || "");
      setIsEditingBeforeSave(false);

    } catch (error) {
      setStatus("保存に失敗しました: " + (error instanceof Error ? error.message : ""));
    }
  }; */

  const resetState = () => {
    setSelectedRecording(null);
    setTitle("");
    setTranscript("");
    setSummary("");
    setKeywords([]);
    setShowAudioPlayer(false);
    setIsEditingBeforeSave(false);
    setAudioChunks([]);
    setCurrentChunkIndex(0);
    setUploadedAudioUrl("");
    setRecordingDuration("0:00");
    setErrorMessage(null);
    setProcessingStatus(null);
    setExecutionArn(null);
  };

  const startRecording = async () => {
    try {
      // 既存の録音データがある場合は状態をリセット
      resetState();
      
      // MediaRecorder の設定を最適化
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,  // モノラル
          sampleRate: 22050  // サンプルレートを下げる
        }
      });
      
      // 既存の state 更新をそのまま使用
      setShowAudioPlayer(false);
      setIsRecording(true);
      setStatus("録音中...");
      
      // MediaRecorder インスタンスを作成
      const options = {
        audioBitsPerSecond: 64000,  // 64kbps
        mimeType: 'audio/webm'  // WebMフォーマットを使用
      };
      
      const recorder = new MediaRecorder(stream, options);
      mediaRecorder.current = recorder;
      
      // データ収集の設定
      recordingChunks.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          recordingChunks.current.push(event.data);
        }
      };
      
      // 録音停止時の処理
      recorder.onstop = async () => {
        // MediaRecorderのストリームを停止
        if (recorder && recorder.stream) {
          recorder.stream.getTracks().forEach(track => track.stop());
        }
        
        // Combine chunks into a single Blob
        const blob = new Blob(recordingChunks.current, { type: 'audio/webm' });
        
        // 直接 Blob を処理
        await processAudio(blob);
      };
      
      // 録音開始時間を記録
      recordingStartTimeRef.current = Date.now();
      
      // 録音時間更新用のインターバル設定
      const interval = setInterval(() => {
        if (recordingStartTimeRef.current !== null) {
          const elapsed = Math.floor((Date.now() - recordingStartTimeRef.current) / 1000);
          setRecordingDuration(elapsed.toString());
        }
      }, 1000);
      
      recordingIntervalRef.current = interval;
      
      // 録音開始
      recorder.start(1000);  // 1秒ごとにデータを取得
      
    } catch (error) {
      console.error("Error starting recording:", error);
      setStatus("録音の開始に失敗しました");
    }
  };

  const stopRecording = async () => {
    try {
      if (!mediaRecorder.current || mediaRecorder.current.state === 'inactive') {
        console.warn('MediaRecorder is not active');
        return;
      }
      
      // 録音を停止
      mediaRecorder.current.stop();
      setIsRecording(false);
      setStatus("録音を停止しました");
      
      // 録音時間の更新を停止
      if (recordingIntervalRef.current) {
        clearInterval(recordingIntervalRef.current);
        recordingIntervalRef.current = null;
      }
      
      // 録音時間を最終的に設定
      if (recordingStartTimeRef.current) {
        const elapsed = Math.floor((Date.now() - recordingStartTimeRef.current) / 1000);
        const minutes = Math.floor(elapsed / 60);
        const seconds = elapsed % 60;
        setRecordingDuration(`${minutes}:${seconds.toString().padStart(2, '0')}`);
      }
      
    } catch (error) {
      console.error("Error stopping recording:", error);
      setStatus("録音の停止に失敗しました");
    }
  };

  const handleRecordButtonClick = () => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  };

  const handleSelectRecording = async (recording: Recording) => {
    setSelectedRecording(recording);
    setTranscript("");
    setSummary("");
    setKeywords([]);
    setCopied(false);
    setIsEditingBeforeSave(false);
    setTitle("");
    setUploadedAudioUrl("");
    setStatus("読み込み中...");
    setIsSidebarOpen(false);
    setShowAudioPlayer(false);

    try {
      await fetchRecording(recording.id);
    } catch (error) {
      setStatus(
        "詳細取得失敗: " + (error instanceof Error ? error.message : "")
      );
    }
  };

  const handleDelete = async () => {
    if (!selectedRecording) return;
    
    try {
      setStatus("削除中...");
      const response = await fetch(`${KOENOTE_API_URL}/koenoto/${selectedRecording.id}`, {
        method: 'DELETE',
      });
      
      if (!response.ok) {
        throw new Error(`削除に失敗しました (status: ${response.status})`);
      }
      
      // 削除成功後、状態をリセット
      resetState();
      
      // 録音一覧を更新
      fetchRecordings();
      setStatus("削除しました");
    } catch (error) {
      setStatus("削除に失敗: " + (error instanceof Error ? error.message : ""));
    }
  };

  const handleKeywordsChange = (val: string) => {
    const arr = val
      .split(/[,\n]/)
      .map((w) => w.trim())
      .filter(Boolean);
    setKeywords(arr);
  };

  const copySummaryToClipboard = () => {
    if (!summary) return;
    navigator.clipboard
      .writeText(summary)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      })
      .catch((err) => {
        console.error("コピーに失敗しました:", err);
      });
  };

  const startPolling = (executionArn: string) => {
    const interval = setInterval(async () => {
      try {
        const response = await fetch(`${KOENOTE_API_URL}/koenoto/process-status?executionArn=${executionArn}`);
        const data = await response.json();
        
        console.log("ポーリングステータス:", data);
        
        if (data.status === 'completed') {
          clearInterval(interval);
          setPollingInterval(null);
          setExecutionArn(null);
          
          // ネストされたJSONを解析
          let resultData = data.result;
          if (resultData && typeof resultData.result === 'string') {
            try {
              resultData = JSON.parse(resultData.result);
              console.log("解析結果データ:", resultData);
            } catch (e) {
              console.error("結果JSONの解析エラー:", e);
            }
          }
          
          // 解析したデータでステートを更新
          setTitle(resultData.title || "無題");
          setTranscript(resultData.transcript || "");
          setSummary(resultData.summary || "");
          setKeywords(resultData.keywords || []);
          
          // Handle audio data
          if (resultData.audioUrl) {
            setUploadedAudioUrl(resultData.audioUrl);
            setShowAudioPlayer(true);
          } else if (resultData.audioChunks && resultData.audioChunks.length > 0) {
            const chunkUrls = resultData.audioChunks.map(
              (key: string) => `https://${AUDIO_BUCKET_NAME}.s3.amazonaws.com/${key}`
            );
            setAudioChunks(chunkUrls);
            setCurrentChunkIndex(0);
            setShowAudioPlayer(true);
          }
          
          setStatus("処理完了");
          setProcessingStatus(null);
          setIsEditingBeforeSave(true);
          
          // 録音リストを更新
          fetchRecordings();
        } else if (data.status === 'failed') {
          clearInterval(interval);
          setPollingInterval(null);
          setExecutionArn(null);
          setStatus(`処理に失敗しました: ${data.error || "不明なエラー"}`);
          setProcessingStatus(null);
        } else {
          // まだ処理中
          const progressMessage = data.message || "処理中...";
          setProcessingStatus(progressMessage);
          
          // 進捗率がある場合は表示
          if (data.percentComplete) {
            setProcessingStatus(`処理中... (${data.percentComplete}%)`);
          }
        }
      } catch (error) {
        console.error("ステータス取得エラー:", error);
        setStatus("ステータスの取得に失敗しました");
        setProcessingStatus(null);
      }
    }, 3000); // 3秒ごとにポーリング
    
    setPollingInterval(interval);
    return interval;
  };

  // コンポーネントのアンマウント時にポーリングを停止
  useEffect(() => {
    return () => {
      if (pollingInterval) {
        clearInterval(pollingInterval);
      }
    };
  }, [pollingInterval]);

  useEffect(() => {
    fetchRecordings();
  }, []);

  const handleAudioEnded = useCallback(() => {
    if (currentChunkIndex < audioChunks.length - 1) {
      // Before changing index, make sure the current audio element is still in the document
      if (audioRef.current && document.body.contains(audioRef.current)) {
        setCurrentChunkIndex(prevIndex => prevIndex + 1);
      }
    } else {
      // Reset to first chunk
      setCurrentChunkIndex(0);
    }
  }, [audioChunks.length, currentChunkIndex]);

  // currentChunkIndex が変更されたら次のチャンクを再生
  useEffect(() => {
    // Only attempt to play if the audio element exists and is in the document
    if (audioRef.current && document.body.contains(audioRef.current)) {
      // Set src first, then load, then play with a small delay
      audioRef.current.src = audioChunks[currentChunkIndex] || '';
      audioRef.current.load();
      
      // Use a small timeout to ensure the audio is loaded before playing
      const playTimeout = setTimeout(() => {
        if (audioRef.current && document.body.contains(audioRef.current)) {
          audioRef.current.play().catch(error => {
            // Only log non-abort errors
            if (error.name !== 'AbortError') {
              console.error('Error playing audio:', error);
            }
          });
        }
      }, 100);
      
      return () => clearTimeout(playTimeout);
    }
  }, [currentChunkIndex, audioChunks]);

  const fetchRecording = async (id: string) => {
    try {
      setStatus("録音データを取得中...");
      const response = await fetch(`${KOENOTE_API_URL}/koenoto/${id}`);
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      console.log("Fetched recording data:", data);
      setSelectedRecording(data);
      
      // audioChunks が存在する場合、URL を生成して設定
      if (data.audioChunks && data.audioChunks.length > 0) {
        const chunkUrls = data.audioChunks.map(
          (key: string) => `https://${AUDIO_BUCKET_NAME}.s3.amazonaws.com/${key}`
        );
        console.log("Generated chunk URLs:", chunkUrls);
        setAudioChunks(chunkUrls);
        setCurrentChunkIndex(0);
        setShowAudioPlayer(true);
        
        // Don't try to immediately load the audio - the effect will handle it
      } else if (data.audioUrl) {
        // 完全な音声ファイルがある場合
        setUploadedAudioUrl(data.audioUrl);
        setShowAudioPlayer(true);
      } else {
        // No audio available
        setShowAudioPlayer(false);
      }
      
      setTranscript(data.transcript || "");
      setSummary(data.summary || "");
      setKeywords(data.keywords || []);
      setTitle(data.title || "");
      setStatus("");
    } catch (error) {
      setStatus("録音データの取得に失敗しました: " + (error instanceof Error ? error.message : ""));
    }
  };

  const AudioPlayer = () => {
    if (!showAudioPlayer) {
      return null; // 音声プレーヤーを表示しない
    }
    
    // 音声URLもチャンクも存在しない場合は音声プレーヤーを表示しない
    if (!uploadedAudioUrl && audioChunks.length === 0 && (!selectedRecording?.audioUrl)) {
      return (
        <div className="space-y-2 sm:space-y-3">
          <h3 className="text-xs sm:text-sm font-medium uppercase tracking-wide text-zinc-300">
            音声
          </h3>
          <p className="text-sm text-zinc-400">音声データがありません</p>
        </div>
      );
    }
    
    return (
      <div className="space-y-2 sm:space-y-3">
        <h3 className="text-xs sm:text-sm font-medium uppercase tracking-wide text-zinc-300">
          音声
        </h3>
        <audio
          ref={audioRef}
          controls
          className="w-full"
          onEnded={handleAudioEnded}
          src={audioChunks.length > 0 ? audioChunks[currentChunkIndex] : (uploadedAudioUrl || selectedRecording?.audioUrl)}
        >
          お使いのブラウザは音声再生をサポートしていません。
        </audio>
      </div>
    );
  };

  // Either use or remove the checkProcessingStatus function
  // If you're not using it, you can comment it out or remove it
  /* const checkProcessingStatus = async () => {
    // Function implementation...
  }; */

  const saveRecording = async () => {
    try {
      setIsLoading(true);
      setStatus("サーバーに保存中...");
      
      // Prepare the recording data
      const recordingData = {
        id: currentProcessingSessionId || uuid(),
        title: title || "無題",
        date: new Date().toISOString().split('T')[0],
        start_time: recordingStartTime ? recordingStartTime.toTimeString().split(' ')[0] : new Date().toTimeString().split(' ')[0],
        duration: recordingDuration && recordingDuration !== 'N/A' ? recordingDuration : "00:00:00",
        transcript: transcript || "",
        summary: summary || "",
        keywords: keywords || [],
        user_id: USER_ID,
        audioUrl: uploadedAudioUrl,
        audioChunksUrls: audioChunks.length > 0 ? audioChunks : undefined,
        timestamp: new Date().toISOString()
      };
      
      // Save the recording
      const response = await fetch(`${KOENOTE_API_URL}/koenoto/save-recording`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          recording: recordingData
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to save recording');
      }

      const savedData = await response.json();
      console.log("Saved recording:", savedData);
      
      // Update the UI
      setIsEditingBeforeSave(false);
      setSelectedRecording(recordingData);

      setShowAudioPlayer(true);
      
      // Refresh the recordings list
      fetchRecordings();
      
      setStatus("保存しました");
    } catch (error) {
      console.error('Error saving recording:', error);
      setStatus("保存に失敗しました: " + (error instanceof Error ? error.message : ""));
      setErrorMessage('録音の保存中にエラーが発生しました。');
    } finally {
      setIsLoading(false);
    }
  };

 
  const playMedia = async (mediaElement: HTMLMediaElement) => {
    try {
      if (mediaElement && document.body.contains(mediaElement)) {
        await mediaElement.play();
      }
    } catch (error: unknown) {
      if (error instanceof Error && error.name !== 'AbortError') {
        console.error('Media playback error:', error);
      }
      // AbortErrors are expected when navigating away, so we can safely ignore them
    }
  };

  // If you're using React hooks, ensure proper cleanup
  useEffect(() => {
    let mediaElement: HTMLMediaElement | null = null;
    
    const setupMedia = async () => {
      mediaElement = document.getElementById('your-media-id') as HTMLMediaElement | null;
      if (mediaElement) {
        try {
          await playMedia(mediaElement);
        } catch (error) {
          console.error('Error playing media:', error);
        }
      }
    };
    
    setupMedia();
    
    // Cleanup function
    return () => {
      if (mediaElement) {
        mediaElement.pause();
        // If needed, remove event listeners here
      }
    };
  }, []);

  return (
    <main className="flex min-h-screen bg-zinc-50 relative">
      {/* モバイル用サイドバー開閉ボタン */}
      <button
        onClick={() => setIsSidebarOpen(!isSidebarOpen)}
        className="md:hidden fixed top-4 right-4 z-50 p-2.5 bg-zinc-900 hover:bg-zinc-800 rounded-full shadow-lg transition-all duration-200 text-white"
        aria-label="Toggle menu"
      >
        <Menu size={20} />
      </button>

      {isSidebarOpen && (
        <div
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 md:hidden transition-opacity duration-300"
          onClick={() => setIsSidebarOpen(false)}
        />
      )}

      {/* サイドバー */}
      <div
        className={`
         fixed md:relative w-72 lg:w-80 bg-white h-screen border-r border-zinc-100 
         transition-all duration-300 ease-in-out z-50
         flex flex-col overflow-hidden shadow-2xl md:shadow-none
         ${isSidebarOpen ? "translate-x-0" : "translate-x-full"} 
         md:translate-x-0 right-0
       `}
      >
        <div className="p-4 sm:p-6 flex-shrink-0">
          <h2 className="text-base font-medium text-zinc-800 mb-4 flex items-center tracking-wide uppercase">
            <Clock className="mr-2" size={18} />
            履歴
          </h2>
        </div>

        <div className="flex-1 overflow-y-auto min-h-0 px-4 sm:px-6 pb-6">
          {recordings.map((rec) => (
            <div
              key={rec.id}
              className={`mb-1 px-3 py-2 sm:py-3 cursor-pointer transition-all rounded-md ${
                selectedRecording?.id === rec.id
                  ? "bg-zinc-100"
                  : "hover:bg-zinc-50"
              }`}
              onClick={() => handleSelectRecording(rec)}
            >
              <div className="flex justify-between items-start">
                <div className="flex-1">
                  <h3
                    className={`font-medium text-sm sm:text-base ${
                      selectedRecording?.id === rec.id
                        ? "text-zinc-900"
                        : "text-zinc-700"
                    }`}
                  >
                    {rec.title || "(無題)"}
                  </h3>
                  <p
                    className={`text-xs sm:text-sm mt-1 ${
                      selectedRecording?.id === rec.id
                        ? "text-zinc-600"
                        : "text-zinc-500"
                    }`}
                  >
                    録音開始日時: {formatDateTime(rec.date, rec.start_time)}
                  </p>
                  <p
                    className={`text-xs sm:text-sm ${
                      selectedRecording?.id === rec.id
                        ? "text-zinc-600"
                        : "text-zinc-500"
                    }`}
                  >
                    録音時間: {rec.duration}
                  </p>
                </div>
                <ChevronRight
                  className={
                    selectedRecording?.id === rec.id
                      ? "text-zinc-400"
                      : "text-zinc-300"
                  }
                  size={16}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* メインエリア */}
      <div className="flex-1 overflow-y-auto bg-zinc-50 w-full md:w-auto">
        <div className="max-w-4xl mx-auto p-4 sm:p-6 lg:p-8 pt-16 md:pt-8 space-y-4 sm:space-y-6">
          <div className="flex items-center justify-between mb-4 sm:mb-8">
            <h1 className="text-xl sm:text-2xl font-semibold tracking-tight text-zinc-900">
              KOENOTO
            </h1>
          </div>

          <div className="space-y-4 sm:space-y-8">
            {/* 録音ボタン */}
            <div className="flex justify-center">
              <RecordButton
                isRecording={isRecording}
                onClick={handleRecordButtonClick}
              />
            </div>

            {/* ステータス表示 */}
            <StatusIndicator status={status} processingStatus={processingStatus} />

            {/* 録音内容の編集(サーバー保存前) */}
            {isEditingBeforeSave && (
              <div className="bg-white rounded-lg border border-zinc-200 p-4 sm:p-6 shadow-sm space-y-4">
                <h2 className="text-base sm:text-lg font-medium text-zinc-800 mb-2">
                  録音結果の確認・編集
                </h2>

                {/* Add audio player at the top of the form */}
                {showAudioPlayer && <AudioPlayer />}

                <div>
                  <label className="block text-sm font-medium text-zinc-700 mb-1">
                    タイトル
                  </label>
                  <input
                    type="text"
                    className="w-full border border-zinc-300 rounded px-3 py-2 text-sm text-zinc-700"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-zinc-700 mb-1">
                    文字起こし
                  </label>
                  <textarea
                    rows={3}
                    className="w-full border border-zinc-300 rounded px-3 py-2 text-sm text-zinc-700"
                    value={transcript}
                    onChange={(e) => setTranscript(e.target.value)}
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-zinc-700 mb-1">
                    要約
                  </label>
                  <textarea
                    rows={3}
                    className="w-full border border-zinc-300 rounded px-3 py-2 text-sm text-zinc-700"
                    value={summary}
                    onChange={(e) => setSummary(e.target.value)}
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-zinc-700 mb-1">
                    キーワード (カンマ or 改行区切り)
                  </label>
                  <textarea
                    rows={2}
                    className="w-full border border-zinc-300 rounded px-3 py-2 text-sm text-zinc-700"
                    value={keywords.join(", ")}
                    onChange={(e) => handleKeywordsChange(e.target.value)}
                  />
                </div>

                <div className="flex justify-end gap-3">
                  <button
                    onClick={() => {
                      setTitle("");
                      setTranscript("");
                      setSummary("");
                      setKeywords([]);
                      setIsEditingBeforeSave(false);
                      setRecordingStartTime(null);
                      setRecordingDuration("0:00");
                      setUploadedAudioUrl("");
                    }}
                    className="px-4 py-2 text-sm rounded border border-zinc-300 bg-zinc-50 text-zinc-700 hover:bg-zinc-100"
                  >
                    キャンセル
                  </button>
                  <button
                    onClick={saveRecording}
                    className="px-4 py-2 bg-zinc-900 text-white rounded hover:bg-zinc-700 transition-colors"
                    disabled={isLoading}
                  >
                    {isLoading ? "保存中..." : "保存"}
                  </button>
                </div>
              </div>
            )}

            {/* 録音内容の表示(サーバー保存後) */}
            {!isEditingBeforeSave && (
              <>
                {/* 文字起こし表示 */}
                <div className="bg-white rounded-lg border border-zinc-200 p-4 sm:p-6 shadow-sm">
                  <div className="flex items-center mb-3 sm:mb-4">
                    <FileText className="mr-2 text-zinc-600" size={18} />
                    <h2 className="text-base sm:text-lg font-medium text-zinc-800">
                      文字起こし
                    </h2>
                    {selectedRecording && (
                      <span className="ml-auto text-sm text-zinc-500">
                        {formatDateTime(
                          selectedRecording.date,
                          selectedRecording.start_time
                        )}
                        ({selectedRecording.duration})
                      </span>
                    )}
                  </div>
                  <p className="text-sm sm:text-base text-zinc-600 leading-relaxed whitespace-pre-line">
                    {transcript}
                  </p>
                </div>

                {/* 要約表示 */}
                <div className="bg-zinc-900 rounded-lg p-4 sm:p-6 lg:p-8 text-white shadow-lg">
                  <div className="flex items-center justify-between mb-4 sm:mb-6">
                    <div className="flex items-center">
                      <FileSearch className="mr-2 text-zinc-200" size={18} />
                      <h2 className="text-base sm:text-lg font-medium text-zinc-100">
                        要約
                      </h2>
                    </div>
                    {selectedRecording && (
                      <button
                        onClick={handleDelete}
                        className="bg-zinc-800 hover:bg-zinc-700 text-white px-3 py-1.5 rounded flex items-center text-sm"
                      >
                        <Trash2 className="mr-1" size={16} />
                        削除
                      </button>
                    )}
                  </div>

                  <div className="space-y-4 sm:space-y-6">
                    <div className="space-y-2 sm:space-y-3">
                      <div className="flex items-center justify-between">
                        <h3 className="text-xs sm:text-sm font-medium uppercase tracking-wide text-zinc-300">
                          要約
                        </h3>
                        <button
                          onClick={copySummaryToClipboard}
                          className="text-xs sm:text-sm px-2 py-1 rounded bg-zinc-600 hover:bg-zinc-500 text-white flex items-center"
                        >
                          {copied ? (
                            <>
                              <Check className="mr-1" size={16} />
                              Copied!
                            </>
                          ) : (
                            "Copy"
                          )}
                        </button>
                      </div>
                      <p className="text-sm sm:text-base text-zinc-200 leading-relaxed bg-zinc-600/30 p-3 sm:p-4 rounded-lg border border-zinc-600/50">
                        {summary}
                      </p>
                    </div>

                    <div className="space-y-2 sm:space-y-3">
                      <h3 className="text-xs sm:text-sm font-medium uppercase tracking-wide text-zinc-300">
                        キーワード
                      </h3>
                      <div className="flex flex-wrap gap-2">
                        {keywords.length > 0 ? (
                          keywords.map((keyword) => (
                            <span
                              key={keyword}
                              className="px-2 sm:px-3 py-1 rounded-full text-xs sm:text-sm bg-zinc-600/50 text-zinc-200 border border-zinc-500"
                            >
                              {keyword}
                            </span>
                          ))
                        ) : (
                          <span className="text-sm text-zinc-200">
                            キーワードはありません
                          </span>
                        )}
                      </div>
                    </div>
                    {/* 音声プレイヤー */}
                    <AudioPlayer />
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </main>
  );
};

export default KoenotoApp;

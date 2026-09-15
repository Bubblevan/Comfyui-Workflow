# 本地模型目录

本目录属于 `E:\MinimaxH3` 的运行时资产，模型文件保留在 E 盘但不提交到 Git。

当前 H3 工作流使用：

- `diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors`
- `text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`
- `vae/minimax_h3_video_vae_fp16.safetensors`
- `vae/minimax_h3_audio_vae_fp32.safetensors`
- `loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors`

路径由 `ComfyUI/extra_model_paths.yaml` 管理，不应再指向仓库外模型目录。

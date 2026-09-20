package com.example.collegedigitalwallet.model

data class OfflineTokenItem(
    val token_id: String,
    val nonce: String,
    val expires_at: String,
    val signature: String,
    val max_amount: Double
)
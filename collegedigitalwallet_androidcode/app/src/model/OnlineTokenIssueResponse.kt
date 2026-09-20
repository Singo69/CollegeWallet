package com.example.collegedigitalwallet.model

data class OnlineTokenIssueResponse(
    val status: String,
    val message: String,
    val token_id: String? = null,
    val nonce: String? = null,
    val expires_at: String? = null,
    val signature: String? = null
)
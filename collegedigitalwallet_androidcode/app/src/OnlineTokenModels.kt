package com.example.collegedigitalwallet


data class OnlineTokenIssueRequest(
    val sender_username: String,
    val merchant_username: String,
    val amount: Double,
    val note: String? = null
)

data class OnlineTokenIssueResponse(
    val status: String,
    val message: String,
    val token_id: String? = null,
    val nonce: String? = null,
    val expires_at: String? = null,
    val signature: String? = null
)

data class OnlineTokenConsumeRequest(
    val token_id: String,
    val nonce: String,
    val expires_at: String,
    val signature: String
)